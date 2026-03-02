{
  description = "Aegis Component SDK — C++";

  inputs = {
    nixpkgs.url     = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils, ... }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs { inherit system; };
      in {
        devShells.default = pkgs.mkShell {
          buildInputs = [
            pkgs.cmake
            pkgs.ninja
            pkgs.gcc13       # C++23 support
            pkgs.clang-tools # clangd, clang-format
            pkgs.nlohmann_json
            pkgs.libuuid
            pkgs.pkg-config
          ];

          shellHook = ''
            echo "Aegis C++ SDK dev shell"
            echo "  cmake -B build -G Ninja && ninja -C build   — build"
            echo "  ./build/market_data                          — run example"
          '';
        };
      }
    );
}
