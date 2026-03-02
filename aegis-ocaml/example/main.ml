(** Example: MarketData component using the Aegis OCaml SDK *)

open Aegis_component

let () =
  let cfg = Config.default_config
    ~socket_path:    "/tmp/aegis_components.sock"
    ~session_token:  "YOUR_SESSION_TOKEN_HERE"
    ~component_name: "market_data"
  in
  let cfg = { cfg with
    Config.version              = "0.1.0";
    supported_symbols           = ["BTC/USDT"; "ETH/USDT"];
    supported_timeframes        = ["1m"; "5m"];
    requires_streams            = ["candles"];
    max_reconnect_attempts      = 10;
  } in

  let handlers = { Config.empty_handlers with
    on_configure = Some (fun socket_path topics ->
      Printf.printf "[MarketData] Configuring — socket=%s topics=[%s]\n%!"
        socket_path (String.concat "," topics)
      (* Connect to data stream socket here *)
    );

    on_running = Some (fun ~stop ->
      Printf.printf "[MarketData] Running — starting data worker\n%!";
      let tick = ref 0 in
      while not !stop do
        incr tick;
        Printf.printf "[MarketData] Tick #%d — processing data...\n%!" !tick;
        Unix.sleepf 5.0
      done;
      Printf.printf "[MarketData] Data worker stopped\n%!"
    );

    on_ping = Some (fun () ->
      Printf.printf "[MarketData] PING received\n%!"
    );

    on_shutdown = Some (fun () ->
      Printf.printf "[MarketData] Releasing resources\n%!"
    );

    on_error = Some (fun code message ->
      Printf.eprintf "[MarketData] Error — code=%s message=%s\n%!" code message
    );
  } in

  let component = Client.create cfg handlers in

  (* Handle Ctrl-C *)
  Sys.set_signal Sys.sigint  (Sys.Signal_handle (fun _ -> component.stop_flag := true));
  Sys.set_signal Sys.sigterm (Sys.Signal_handle (fun _ -> component.stop_flag := true));

  Client.run component
