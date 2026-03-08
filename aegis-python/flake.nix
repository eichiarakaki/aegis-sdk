{
  description = "Aegis Project — Python SDK";

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
          # Use 'packages' instead of 'buildInputs' for modern flakes
          packages = with pkgs; [
            # Only the bare essentials to avoid Nix-side dependency hell
            python313
            python313Packages.pip
            python313Packages.virtualenv
            
            # Binary tools that Python libs often need to compile
            pkg-config
            openssl
            stdenv.cc.cc.lib
            
            # Quality of life tools
            ruff
            just
          ];

          shellHook = ''
            # 1. Setup VirtualEnv
            if [ ! -d ".venv" ]; then
              echo "Creating isolated virtualenv..."
              python -m venv .venv
            fi
            source .venv/bin/activate

            # 2. Fix for libraries looking for libstdc++ / zlib
            export LD_LIBRARY_PATH="${pkgs.stdenv.cc.cc.lib}/lib:$LD_LIBRARY_PATH"

            echo -e "\033[1;33mAEGIS PYTHON SDK\033[0m"
            echo "Python $(python --version) | Nix is managing the interpreter only."
          '';
        };
      }
    );
}