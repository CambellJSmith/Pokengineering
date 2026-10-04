#!/usr/bin/env bash
set -euo pipefail

root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)" # Resolve the repository root.
third_party_dir="$root_dir/third_party" # Store the pinned third-party source used by the project.
bin_dir="$root_dir/tools/bin" # Store locally built helper executables.
acf_repo="https://github.com/SombrAbsol/acftool.git" # Upstream Guardian Signs ACF utility.
acf_commit="7a3c294012b59650c1fed290c1d345b8c80977a9" # Pin acftool for reproducible builds.
mes_repo="https://github.com/SombrAbsol/ra23mes.git" # Upstream Guardian Signs MES converter.
mes_commit="1f4291960bbd5350a54bc3de5cd131ab9a273cf2" # Pin ra3mes for reproducible builds.
acf_dir="$third_party_dir/acftool" # Vendored/local acftool source directory.
mes_dir="$third_party_dir/ra23mes" # Vendored/local ra23mes source directory.

require_command() {
    command -v "$1" >/dev/null 2>&1 || { printf 'missing required command: %s\n' "$1" >&2; exit 1; }
}

prepare_dependency() {
    local repository_url="$1"
    local commit_sha="$2"
    local destination="$3"

    if [[ -d "$destination/.git" ]]; then
        git -C "$destination" fetch --depth 1 origin "$commit_sha"
        git -C "$destination" checkout --detach --force "$commit_sha"
        return
    fi

    # The complete project snapshot vendors these pinned source trees without their nested
    # .git directories. Use them directly instead of trying to clone over a non-empty path.
    if [[ -f "$destination/Makefile" && -d "$destination/src" ]]; then
        printf 'using vendored dependency source: %s\n' "$destination"
        return
    fi

    if [[ -e "$destination" ]]; then
        printf 'dependency directory exists but is neither a checkout nor a vendored source tree: %s\n' "$destination" >&2
        exit 1
    fi

    git clone --filter=blob:none --no-checkout "$repository_url" "$destination"
    git -C "$destination" fetch --depth 1 origin "$commit_sha"
    git -C "$destination" checkout --detach --force "$commit_sha"
}

require_command git
require_command make

if ! command -v clang >/dev/null 2>&1 && ! command -v gcc >/dev/null 2>&1; then
    printf 'missing required compiler: install clang or gcc\n' >&2
    exit 1
fi

mkdir -p "$third_party_dir" "$bin_dir"

prepare_dependency "$acf_repo" "$acf_commit" "$acf_dir"
make -C "$acf_dir" clean >/dev/null
make -C "$acf_dir" acftool
install -m 0755 "$acf_dir/build/acftool" "$bin_dir/acftool"

prepare_dependency "$mes_repo" "$mes_commit" "$mes_dir"
make -C "$mes_dir" clean >/dev/null
make -C "$mes_dir" ra3mes
install -m 0755 "$mes_dir/build/ra3mes" "$bin_dir/ra3mes"

printf 'installed tools:\n'
printf '  %s\n' "$bin_dir/acftool"
printf '  %s\n' "$bin_dir/ra3mes"
