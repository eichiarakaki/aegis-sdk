(** Aegis component protocol types and envelope helpers. *)

let protocol_version = "0.1"

type message_type =
  | Control
  | Lifecycle
  | Config
  | Error
  | Heartbeat
  | Data

type command =
  | Register
  | Registered
  | StateUpdate
  | Shutdown
  | Ack
  | Nack
  | Configure
  | Configured
  | Ping
  | Pong
  | RuntimeError
  | RegistrationFailed

type component_state =
  | Init
  | Registered
  | Initializing
  | Ready
  | Configured
  | Running
  | Waiting
  | Error
  | Finished
  | Shutdown

let string_of_message_type = function
  | Control   -> "CONTROL"
  | Lifecycle -> "LIFECYCLE"
  | Config    -> "CONFIG"
  | Error     -> "ERROR"
  | Heartbeat -> "HEARTBEAT"
  | Data      -> "DATA"

let string_of_command = function
  | Register           -> "REGISTER"
  | Registered         -> "REGISTERED"
  | StateUpdate        -> "STATE_UPDATE"
  | Shutdown           -> "SHUTDOWN"
  | Ack                -> "ACK"
  | Nack               -> "NACK"
  | Configure          -> "CONFIGURE"
  | Configured         -> "CONFIGURED"
  | Ping               -> "PING"
  | Pong               -> "PONG"
  | RuntimeError       -> "RUNTIME_ERROR"
  | RegistrationFailed -> "REGISTRATION_FAILED"

let string_of_state = function
  | Init         -> "INIT"
  | Registered   -> "REGISTERED"
  | Initializing -> "INITIALIZING"
  | Ready        -> "READY"
  | Configured   -> "CONFIGURED"
  | Running      -> "RUNNING"
  | Waiting      -> "WAITING"
  | Error        -> "ERROR"
  | Finished     -> "FINISHED"
  | Shutdown     -> "SHUTDOWN"

let command_of_string = function
  | "REGISTER"             -> Register
  | "REGISTERED"           -> Registered
  | "STATE_UPDATE"         -> StateUpdate
  | "SHUTDOWN"             -> Shutdown
  | "ACK"                  -> Ack
  | "NACK"                 -> Nack
  | "CONFIGURE"            -> Configure
  | "CONFIGURED"           -> Configured
  | "PING"                 -> Ping
  | "PONG"                 -> Pong
  | "RUNTIME_ERROR"        -> RuntimeError
  | "REGISTRATION_FAILED"  -> RegistrationFailed
  | s                      -> failwith ("Unknown command: " ^ s)

let message_type_of_string = function
  | "CONTROL"   -> Control
  | "LIFECYCLE" -> Lifecycle
  | "CONFIG"    -> Config
  | "ERROR"     -> Error
  | "HEARTBEAT" -> Heartbeat
  | "DATA"      -> Data
  | s           -> failwith ("Unknown message type: " ^ s)

(** Standard protocol envelope *)
type envelope = {
  protocol_version : string;
  message_id       : string;
  correlation_id   : string option;
  timestamp        : string;
  source           : string;
  target           : string;
  msg_type         : message_type;
  command          : command;
  payload          : Yojson.Safe.t;
}

let utc_now () =
  let t = Unix.gettimeofday () in
  let tm = Unix.gmtime t in
  Printf.sprintf "%04d-%02d-%02dT%02d:%02d:%02dZ"
    (tm.Unix.tm_year + 1900) (tm.Unix.tm_mon + 1) tm.Unix.tm_mday
    tm.Unix.tm_hour tm.Unix.tm_min tm.Unix.tm_sec

let make_envelope msg_type command source payload =
  {
    protocol_version = protocol_version;
    message_id       = Uuidm.(to_string (v4_gen (Random.State.make_self_init ()) ()));
    correlation_id   = None;
    timestamp        = utc_now ();
    source;
    target           = "aegis";
    msg_type;
    command;
    payload;
  }

let with_correlation env id = { env with correlation_id = Some id }

let envelope_to_json env =
  let corr = match env.correlation_id with
    | Some id -> `String id
    | None    -> `Null
  in
  `Assoc [
    "protocol_version", `String env.protocol_version;
    "message_id",       `String env.message_id;
    "correlation_id",   corr;
    "timestamp",        `String env.timestamp;
    "source",           `String env.source;
    "target",           `String env.target;
    "type",             `String (string_of_message_type env.msg_type);
    "command",          `String (string_of_command env.command);
    "payload",          env.payload;
  ]

let envelope_of_json json =
  let open Yojson.Safe.Util in
  {
    protocol_version = json |> member "protocol_version" |> to_string;
    message_id       = json |> member "message_id"       |> to_string;
    correlation_id   = json |> member "correlation_id"   |> to_string_option;
    timestamp        = json |> member "timestamp"        |> to_string;
    source           = json |> member "source"           |> to_string;
    target           = json |> member "target"           |> to_string;
    msg_type         = json |> member "type"             |> to_string |> message_type_of_string;
    command          = json |> member "command"          |> to_string |> command_of_string;
    payload          = json |> member "payload";
  }
