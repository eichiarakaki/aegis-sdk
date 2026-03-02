cmake_minimum_required(VERSION 3.20)
project(aegis-component VERSION 0.1.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 23)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

find_package(nlohmann_json REQUIRED)
find_package(PkgConfig REQUIRED)
pkg_check_modules(UUID REQUIRED uuid)

# Library
add_library(aegis-component
    src/protocol.cpp
    src/client.cpp
)
target_include_directories(aegis-component PUBLIC include)
target_link_libraries(aegis-component PUBLIC nlohmann_json::nlohmann_json ${UUID_LIBRARIES})
target_include_directories(aegis-component PUBLIC ${UUID_INCLUDE_DIRS})

# Example
add_executable(market_data example/market_data.cpp)
target_link_libraries(market_data PRIVATE aegis-component)
