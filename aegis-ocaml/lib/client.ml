(** Aegis component client — handles registration, heartbeat,
    state transitions, and reconnection automatically. *)

open Protocol
open Config

let log_info name msg  = Printf.printf  "[INFO]  [%s] %s\n%!" name msg
let log_warn name msg  = Printf.printf  "[WARN]  [%s] %s\n%!" name msg
let log_error name msg = Printf.eprintf "[ERROR] [%s] %s\n%!" name msg

exception Registration_error of string

type t = {
  cfg          : config;
  handlers     : handlers;
  mutable component_id : string;
  mutable session_id   : string;
  mutable state        : component_state;
  mutable started_at   : float;
  mutable stop_flag    : bool ref;
}

let create cfg handlers = {
  cfg;
  handlers;
  component_id = "";
  session_id   = "";
  state        = Init;
  started_at   = Unix.gettimeofday ();
  stop_flag    = ref false;
}

(* ---------------------------------------------------------------------------
   Low-level send / recv
   --------------------------------------------------------------------------- *)

let send_line oc env =
  let line = Yojson.Safe.to_string (envelope_to_json env) ^ "\n" in
  output_string oc line;
  flush oc

let recv_line ic =
  let line = input_line ic in
  envelope_of_json (Yojson.Safe.from_string line)

(* ---------------------------------------------------------------------------
   Helpers
   --------------------------------------------------------------------------- *)

let source t = "component:" ^ t.cfg.component_name

let send_state_update t oc new_state =
  let payload = `Assoc ["state", `String (string_of_state new_state)] in
  let env = make_envelope Lifecycle StateUpdate (source t) payload in
  send_line oc env;
  t.state <- new_state

let send_ack t oc correlation_id =
  let payload = `Assoc ["status", `String "ok"] in
  let env = make_envelope Control Ack (source t) payload
            |> fun e -> with_correlation e correlation_id in
  send_line oc env

let send_error t oc code message recoverable =
  let payload = `Assoc [
    "code",        `String code;
    "message",     `String message;
    "recoverable", `Bool recoverable;
  ] in
  let env = make_envelope Error RuntimeError (source t) payload in
  send_line oc env

(* ---------------------------------------------------------------------------
   Registration
   --------------------------------------------------------------------------- *)

let do_register t ic oc =
  let caps = `Assoc [
    "supported_symbols",    `List (List.map (fun s -> `String s) t.cfg.supported_symbols);
    "supported_timeframes", `List (List.map (fun s -> `String s) t.cfg.supported_timeframes);
    "requires_streams",     `List (List.map (fun s -> `String s) t.cfg.requires_streams);
  ] in
  let payload = `Assoc [
    "session_token",  `String t.cfg.session_token;
    "component_name", `String t.cfg.component_name;
    "version",        `String t.cfg.version;
    "capabilities",   caps;
  ] in
  let env = make_envelope Lifecycle Register (source t) payload in
  send_line oc env;

  let resp = recv_line ic in
  if resp.command <> Registered then
    raise (Registration_error (Printf.sprintf "unexpected response: %s"
      (string_of_command resp.command)));

  let open Yojson.Safe.Util in
  t.component_id <- resp.payload |> member "component_id" |> to_string;
  t.session_id   <- resp.payload |> member "session_id"   |> to_string;
  t.state        <- Registered;

  log_info t.cfg.component_name
    (Printf.sprintf "Registered — component_id=%s session_id=%s"
      t.component_id t.session_id)

(* ---------------------------------------------------------------------------
   Message handlers
   --------------------------------------------------------------------------- *)

let handle_heartbeat t oc env =
  if env.command = Ping then begin
    Option.iter (fun f -> f ()) t.handlers.on_ping;
    let uptime = int_of_float (Unix.gettimeofday () -. t.started_at) in
    let payload = `Assoc [
      "state",          `String (string_of_state t.state);
      "uptime_seconds", `Int uptime;
    ] in
    let pong = make_envelope Heartbeat Pong (source t) payload
               |> fun e -> with_correlation e env.message_id in
    send_line oc pong
  end

let handle_config t ic oc env =
  if env.command = Configure then begin
    let open Yojson.Safe.Util in
    let sock   = env.payload |> member "data_stream_socket" |> to_string_option |> Option.value ~default:"" in
    let topics = env.payload |> member "topics" |> to_list |> List.map to_string in

    log_info t.cfg.component_name
      (Printf.sprintf "Configuring — socket=%s topics=[%s]" sock (String.concat "," topics));

    Option.iter (fun f -> f sock topics) t.handlers.on_configure;
    send_ack t oc env.message_id;

    send_state_update t oc Configured;
    send_state_update t oc Running;

    log_info t.cfg.component_name "Component is now RUNNING";

    let stop = ref false in
    t.stop_flag <- stop;
    Option.iter (fun f ->
      let _ = Thread.create (fun () -> f ~stop) () in ()
    ) t.handlers.on_running
  end

(* Returns true if the loop should stop *)
let handle_lifecycle t oc env =
  match env.command with
  | Shutdown ->
    log_info t.cfg.component_name "Shutdown requested by Aegis";
    send_ack t oc env.message_id;
    true
  | Ack -> false
  | _   ->
    log_warn t.cfg.component_name
      (Printf.sprintf "Unknown lifecycle command: %s" (string_of_command env.command));
    false

(* Returns true if non-recoverable *)
let handle_error_msg t env =
  let open Yojson.Safe.Util in
  let code        = env.payload |> member "code"        |> to_string_option |> Option.value ~default:"UNKNOWN" in
  let message     = env.payload |> member "message"     |> to_string_option |> Option.value ~default:"" in
  let recoverable = env.payload |> member "recoverable" |> to_bool_option   |> Option.value ~default:false in
  log_error t.cfg.component_name
    (Printf.sprintf "Error — code=%s message=%s" code message);
  Option.iter (fun f -> f code message) t.handlers.on_error;
  not recoverable

(* ---------------------------------------------------------------------------
   Graceful shutdown
   --------------------------------------------------------------------------- *)

let graceful_shutdown t oc =
  log_info t.cfg.component_name "Shutting down...";
  t.stop_flag := true;
  Option.iter (fun f -> f ()) t.handlers.on_shutdown;
  (try
    let env = make_envelope Lifecycle Shutdown (source t) (`Assoc []) in
    send_line oc env
  with _ -> ());
  t.state <- Shutdown;
  log_info t.cfg.component_name "Shutdown complete"

(* ---------------------------------------------------------------------------
   Message loop
   --------------------------------------------------------------------------- *)

let message_loop t ic oc =
  let rec loop () =
    let env = recv_line ic in
    let stop = match env.msg_type with
      | Heartbeat -> handle_heartbeat t oc env; false
      | Config    -> handle_config t ic oc env; false
      | Lifecycle -> handle_lifecycle t oc env
      | Error     ->
        if handle_error_msg t env then
          failwith "non-recoverable error from Aegis"
        else false
      | _         ->
        log_warn t.cfg.component_name
          (Printf.sprintf "Unknown message type: %s" (string_of_message_type env.msg_type));
        false
    in
    if not stop then loop ()
  in
  loop ();
  graceful_shutdown t oc

(* ---------------------------------------------------------------------------
   run_once — single connection attempt
   --------------------------------------------------------------------------- *)

let run_once t =
  t.started_at <- Unix.gettimeofday ();
  let sock = Unix.(socket PF_UNIX SOCK_STREAM 0) in
  let addr = Unix.ADDR_UNIX t.cfg.socket_path in
  log_info t.cfg.component_name ("Connecting to " ^ t.cfg.socket_path);
  Unix.connect sock addr;
  log_info t.cfg.component_name "Connected";
  let ic = Unix.in_channel_of_descr sock in
  let oc = Unix.out_channel_of_descr sock in
  Fun.protect
    ~finally:(fun () -> Unix.close sock)
    (fun () ->
      do_register t ic oc;
      message_loop t ic oc)

(* ---------------------------------------------------------------------------
   run — with reconnection
   --------------------------------------------------------------------------- *)

let run t =
  let attempts = ref 0 in
  let delay    = ref t.cfg.reconnect_delay_s in
  let continue = ref true in
  while !continue do
    (try
      run_once t;
      continue := false  (* clean exit *)
    with
    | Registration_error msg ->
      log_error t.cfg.component_name ("Registration failed (will not retry): " ^ msg);
      continue := false
    | exn ->
      log_warn t.cfg.component_name
        (Printf.sprintf "Disconnected: %s" (Printexc.to_string exn));
      if not t.cfg.reconnect then continue := false
      else begin
        incr attempts;
        if t.cfg.max_reconnect_attempts > 0
          && !attempts >= t.cfg.max_reconnect_attempts then begin
          log_error t.cfg.component_name
            (Printf.sprintf "Max reconnect attempts (%d) reached" !attempts);
          continue := false
        end else begin
          log_info t.cfg.component_name
            (Printf.sprintf "Reconnecting in %.0fs (attempt %d)..." !delay !attempts);
          Unix.sleepf !delay;
          delay := Float.min (!delay *. 2.0) t.cfg.max_reconnect_delay_s
        end
      end)
  done
