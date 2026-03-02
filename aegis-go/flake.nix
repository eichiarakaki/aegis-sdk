{
  description = "Aegis Project — Go Backend SDK";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    utils.url   = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, utils }:
    utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs { inherit system; };
      in {
        devShells.default = pkgs.mkShell {
          buildInputs = with pkgs; [
            go_1_26
            golangci-lint
            delve
            gopls
            gofumpt
            just
          ];

          shellHook = ''
            export GOBIN="$(pwd)/.bin"
            export PATH="$GOBIN:$PATH"
            echo -e "\033[1;34mAEGIS GO CORE\033[0m"
            echo "Go $(go version | cut -d ' ' -f3) ready."
          '';
        };
      }
    );
}