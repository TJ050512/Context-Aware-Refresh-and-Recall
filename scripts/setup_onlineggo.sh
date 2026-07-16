#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
target="${1:-${repo_root}/external/OnlineGGO}"
upstream="https://github.com/zanghz21/OnlineGGO.git"
revision="ff6d830e2fd5bf85ccbb72eaec0fb8df1cf1c256"
patch_file="${repo_root}/patches/onlineggo-local.patch"
config_source="${repo_root}/patches/onlineggo_configs"
config_target="${target}/CMAES/config/traffic_mapf/period_online"

if [[ -e "${target}" ]]; then
  echo "Refusing to overwrite existing path: ${target}" >&2
  exit 1
fi

mkdir -p "$(dirname -- "${target}")"
git clone --recurse-submodules "${upstream}" "${target}"
git -C "${target}" checkout --detach "${revision}"
git -C "${target}" submodule update --init --recursive
git -C "${target}" apply "${patch_file}"
cp "${config_source}"/*.gin "${config_target}/"

echo "OnlineGGO reconstructed at ${target}"
echo "Pinned upstream revision: ${revision}"
