(** Configuration and handler callbacks for Aegis components. *)

type config = {
  socket_path             : string;
  session_token           : string;
  component_name          : string;
  version                 : string;
  supported_symbols       : string list;
  supported_timeframes    : string list;
  requires_streams        : string list;
  reconnect               : bool;
  reconnect_delay_s       : float;
  max_reconnect_delay_s   : float;
  max_reconnect_attempts  : int;   (* 0 = unlimited *)
}

let default_config ~socket_path ~session_token ~component_name = {
  socket_path;
  session_token;
  component_name;
  version                = "0.1.0";
  supported_symbols      = [];
  supported_timeframes   = [];
  requires_streams       = [];
  reconnect              = true;
  reconnect_delay_s      = 3.0;
  max_reconnect_delay_s  = 60.0;
  max_reconnect_attempts = 0;
}

(** All handler callbacks — all are optional (default: no-op). *)
type handlers = {
  (** Called when Aegis sends CONFIGURE. *)
  on_configure : (string -> string list -> unit) option;

  (** Called after the component transitions to RUNNING.
      Should spawn a background Domain/Thread and respect the stop ref. *)
  on_running   : (stop:bool ref -> unit) option;

  (** Called on every PING before the PONG is sent. *)
  on_ping      : (unit -> unit) option;

  (** Called just before the component disconnects. *)
  on_shutdown  : (unit -> unit) option;

  (** Called when Aegis sends a non-recoverable ERROR. *)
  on_error     : (string -> string -> unit) option;
}

let empty_handlers = {
  on_configure = None;
  on_running   = None;
  on_ping      = None;
  on_shutdown  = None;
  on_error     = None;
}

let invoke_opt f = Option.iter (fun fn -> fn ()) f
let invoke1_opt f x = Option.iter (fun fn -> fn x) f
