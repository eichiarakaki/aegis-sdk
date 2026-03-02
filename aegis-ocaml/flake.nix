{
  description = "Aegis Component SDK — OCaml";

  inputs = {
    nixpkgs.url     = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils, ... }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs   = import nixpkgs { inherit system; };
        ocaml  = pkgs.ocaml-ng.ocamlPackages_5_2;
      in {
        devShells.default = pkgs.mkShell {
          buildInputs = [
            ocaml.ocaml
            ocaml.dune_3
            ocaml.ocaml-lsp
            ocaml.ocamlformat
            ocaml.yojson
            ocaml.uuidm
            pkgs.opam
          ];

          shellHook = ''
            echo "Aegis OCaml SDK dev shell"
            echo "  dune build          — build library + example"
            echo "  dune exec example/main.exe — run example"
            echo "  dune test           — run tests"
          '';
        };
      }
    );
}
