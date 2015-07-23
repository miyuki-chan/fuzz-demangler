#!/bin/bash -e
PROJ_DIR=$(readlink -e "$(dirname $0)")
TMP="${PROJ_DIR}/tmp"
mkdir -p "${TMP}"

export AFL_CC=/opt/gcc-4.9.3-fdo/bin/gcc

for BUILD_TYPE in afl asan rel debug
do
    BUILD_DIR="${PROJ_DIR}/build_${BUILD_TYPE}"
    rm -rf "${BUILD_DIR}"
    mkdir -p "${BUILD_DIR}"
    CMAKE_BTYPE='Release'
    [[ ${BUILD_TYPE} == debug ]] && CMAKE_BTYPE='Debug' || CMAKE_BTYPE='Release'
    [[ ${BUILD_TYPE} == asan ]] && CMAKE_ASAN='ON' || CMAKE_ASAN='OFF'
    [[ ${BUILD_TYPE} == afl ]] && CMAKE_AFL='ON' || CMAKE_AFL='OFF'
    cd "${BUILD_DIR}"
    cmake -DCMAKE_BUILD_TYPE=${CMAKE_BTYPE} -DASAN=${CMAKE_ASAN} -DAFL=${CMAKE_AFL} ..
    make -j$(nproc) cp-demangle VERBOSE=1
done

cp -f "${PROJ_DIR}/build_afl/cp-demangle" "${TMP}/"
cp -rf "${PROJ_DIR}/tests" "${TMP}/"
mkdir -p "${TMP}/output"

