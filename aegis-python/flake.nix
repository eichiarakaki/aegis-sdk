{
  description = "Aegis Project — Python Research SDK";

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
            (python311.withPackages (ps: with ps; [ 
              pip 
              virtualenv 
              setuptools
            ]))
            ruff
            pyright   
            just
            pkg-config
            openssl  
          ];

          shellHook = ''
            if [ ! -d ".venv" ]; then
              echo "Initializing virtualenv..."
              python -m venv .venv
            fi
            source .venv/bin/activate
            echo -e "\033[1;33mAEGIS PYTHON SDK\033[0m"
            echo "Python $(python --version) + Nix isolation"
          '';
        };
      }
    );
}