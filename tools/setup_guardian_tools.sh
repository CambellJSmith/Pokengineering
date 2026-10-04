#!/usr/bin/env bash
set -euo pipefail

root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)" # Resolve the repository root.
third_party_dir="$root_dir/third_party" # Store downloaded third-party source outside version control.
bin_dir="$root_dir/tools/bin" # Store locally built helper executables outside version control.
acf_repo="https://github.com/SombrAbsol/acftool.git" # Use the maintained Guardian Signs ACF utility.
acf_commit="7a3c294012b59650c1fed290c1d345b8c80977a9" # Pin acftool for reproducible builds.
mes_repo="https://github.com/SombrAbsol/ra23mes.git" # Use the maintained Guardian Signs MES converter.
mes_commit="1f4291960bbd5350a54bc3de5cd131ab9a273cf2" # Pin ra3mes for reproducible builds.
acf_dir="$third_party_dir/acftool" # Keep the acftool checkout in the local dependency directory.
mes_dir="$third_party_dir/ra23mes" # Keep the ra23mes checkout in the local dependency directory.

require_command() { # Fail early when a required command is unavailable.
    command -v "$1" >/dev/null 2>&1 || { printf 'missing required command: %s\n' "$1" >&2; exit 1; }
}

checkout_dependency() { # Clone or refresh a dependency and check out the pinned revision.
    local repository_url="$1" # Receive the dependency repository URL.
    local commit_sha="$2" # Receive the exact revision to use.
    local destination="$3" # Receive the local checkout directory.

    if [[ ! -d "$destination/.git" ]]; then # Clone the dependency only when no checkout exists.
        git clone --filter=blob:none --no-checkout "$repository_url" "$destination"
    fi

    git -C "$destination" fetch --depth 1 origin "$commit_sha" # Fetch only the pinned revision.
    git -C "$destination" checkout --detach --force "$commit_sha" # Use the pinned revision exactly.
}

require_command git # Git downloads the two maintained tools.
require_command make # Make builds both tools.

if ! command -v clang >/dev/null 2>&1 && ! command -v gcc >/dev/null 2>&1; then # Require a supported C compiler.
    printf 'missing required compiler: install clang or gcc\n' >&2
    exit 1
fi

mkdir -p "$third_party_dir" "$bin_dir" # Create local dependency and executable directories.

checkout_dependency "$acf_repo" "$acf_commit" "$acf_dir" # Prepare acftool at the pinned revision.
make -C "$acf_dir" clean >/dev/null # Remove stale acftool build products.
make -C "$acf_dir" acftool # Build the ACF extractor/rebuilder.
install -m 0755 "$acf_dir/build/acftool" "$bin_dir/acftool" # Install the local acftool executable.

checkout_dependency "$mes_repo" "$mes_commit" "$mes_dir" # Prepare ra23mes at the pinned revision.
make -C "$mes_dir" clean >/dev/null # Remove stale ra23mes build products.
make -C "$mes_dir" ra3mes # Build only the Guardian Signs MES converter.
install -m 0755 "$mes_dir/build/ra3mes" "$bin_dir/ra3mes" # Install the local ra3mes executable.

printf 'installed tools:\n' # Summarize the generated local executables.
printf '  %s\n' "$bin_dir/acftool" # Report the ACF tool path.
printf '  %s\n' "$bin_dir/ra3mes" # Report the MES converter path.
