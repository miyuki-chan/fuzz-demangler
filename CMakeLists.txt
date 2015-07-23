project(demangler)
cmake_minimum_required(VERSION 2.8)
add_definitions(-DHAVE_CONFIG_H -DSTANDALONE_DEMANGLER -DCHECK_DEMANGLER)
option(AFL      "Compile with 'american fuzzy lop' instrumentation")
option(ASAN     "Compile with 'address sanitizer' instrumentation/library")

if(AFL)
    set(CMAKE_C_COMPILER "afl-gcc")
endif()

set(CMAKE_C_FLAGS "${CMAKE_C_FLAGS} -Wall -Wextra -Wtype-limits")

if(ASAN)
    set(CMAKE_C_FLAGS "${CMAKE_C_FLAGS} -fsanitize=address")
    set(CMAKE_C_FLAGS_DEBUG "-O0 -ggdb2")
else()
    set(CMAKE_C_FLAGS_DEBUG "-O0 -ggdb3 -DCP_DEMANGLE_DEBUG")
endif()

set(CMAKE_C_FLAGS_RELEASE "-O3")

add_executable(cp-demangle  libiberty/cp-demangle.c
                            libiberty/xmalloc.c
                            libiberty/xexit.c
                            libiberty/dyn-string.c)
if(ASAN)
    target_link_libraries(cp-demangle asan)
endif()
