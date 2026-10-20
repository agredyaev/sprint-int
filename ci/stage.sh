#!/usr/bin/env bash
# Stage only reviewed static assets and Quick-sealed Parquet releases.
# SHA-256 guards consistency, not semantic validity or signer authenticity.
set -euo pipefail
shopt -s nullglob
cd "$(dirname "$0")/.."
source_dir="${1:-data}"
output_dir="${2:-_site}"
[[ -d "$source_dir/sprints" ]] || { echo 'Missing sprint data directory' >&2; exit 1; }
[[ -f "$source_dir/manifest.json" && ! -L "$source_dir/manifest.json" ]] || { echo 'Missing release manifest' >&2; exit 1; }
command -v jq >/dev/null || { echo 'jq required on GitHub Actions runner' >&2; exit 1; }
command -v sha256sum >/dev/null || { echo 'sha256sum required on GitHub Actions runner' >&2; exit 1; }
manifest="$source_dir/manifest.json"
# Reject unexpected keys and malformed metadata; no eval, no filenames from unsanitized input.
jq -e -f ci/manifest.jq "$manifest" >/dev/null || {
 echo 'Invalid Parquet release manifest' >&2; exit 1;
}
[[ ! -L "$source_dir" && ! -L "$source_dir/sprints" ]] || { echo 'Symlinked data directories are forbidden' >&2; exit 1; }
files=("$source_dir"/sprints/*.parquet)
manifest_count="$(jq '.sprints|length' "$manifest")"
(( ${#files[@]} == manifest_count )) || { echo 'Sprint file set differs from manifest' >&2; exit 1; }
expected=("$source_dir/history.parquet")
while IFS= read -r id; do
 expected+=("$source_dir/sprints/$id.parquet")
done <<< "$(jq -r '.sprints[].id' "$manifest")"
# Unknown files anywhere in data are not permitted (including dotfiles and links).
find "$source_dir" -mindepth 1 \( -type f -o -type l \) -print0 | while IFS= read -r -d '' f; do
 case "$f" in
   "$source_dir/manifest.json") ;;
   "$source_dir/history.parquet") ;;
   "$source_dir"/sprints/*.parquet)
     found=false
     for approved in "${expected[@]}"; do [[ "$f" == "$approved" ]] && found=true && break; done
     "$found" || { echo "Unexpected data file: $f" >&2; exit 1; };;
   *) echo "Unexpected data file: $f" >&2; exit 1;;
 esac
done
for f in "${expected[@]}"; do
 [[ -f "$f" && ! -L "$f" ]] || { echo "Missing/symlinked Parquet: $f" >&2; exit 1; }
 relative="${f#"$source_dir"/}"
 metadata="$(jq -c --arg f "$relative" 'if .history.path==$f then .history else (.sprints[]|select(.path==$f)) end' "$manifest")"
 [[ -n "$metadata" ]] || { echo "Unlisted Parquet: $f" >&2; exit 1; }
 size="$(jq -r '.size' <<< "$metadata")"
 digest="$(jq -r '.sha256' <<< "$metadata")"
 [[ $(wc -c < "$f" | tr -d ' ') == "$size" ]] || { echo "Parquet size mismatch: $f" >&2; exit 1; }
 [[ $(sha256sum "$f" | cut -d ' ' -f1) == "$digest" ]] || { echo "Parquet checksum mismatch: $f" >&2; exit 1; }
 [[ $(head -c 4 "$f") == PAR1 && $(tail -c 4 "$f") == PAR1 ]] || { echo "Parquet magic mismatch: $f" >&2; exit 1; }
done
# No other static files may be published, even if accidentally committed.
static=(site/index.html site/assets/app.js site/assets/data-store.js site/assets/styles.css)
for required in "${static[@]}"; do
 [[ -f "$required" && ! -L "$required" ]] || { echo "Missing static file: $required" >&2; exit 1; }
done
find site -mindepth 1 \( -type f -o -type l \) -print0 | while IFS= read -r -d '' file; do
 approved=false
 for entry in "${static[@]}"; do [[ "$file" == "$entry" ]] && approved=true && break; done
 "$approved" || { echo "Unexpected site file: $file" >&2; exit 1; }
done
# Never remove an arbitrary directory supplied through the staging argument.
# A prior output is replaceable only when it carries our own staging marker.
if [[ -z "$output_dir" || "$output_dir" == / || "$output_dir" == . || "$output_dir" == ..       || "$output_dir" == *"/../"* || "$output_dir" == *"/./"*       || "$output_dir" == ../* || "$output_dir" == */.. || "$output_dir" == */. ]]; then
  echo 'Unsafe stage output path' >&2; exit 1
fi
if [[ -L "$output_dir" ]]; then
  echo 'Symlinked stage output is forbidden' >&2; exit 1
fi
if [[ -e "$output_dir" ]]; then
  [[ -d "$output_dir" && -f "$output_dir/.sprint-intelligence-stage"      && ! -L "$output_dir/.sprint-intelligence-stage" ]] || {
    echo 'Refusing to overwrite an unmarked directory' >&2; exit 1
  }
fi
rm -rf -- "$output_dir"
mkdir -p "$output_dir/assets" "$output_dir/data/sprints"
cp site/index.html "$output_dir/"
cp site/assets/{app.js,data-store.js,styles.css} "$output_dir/assets/"
cp "$manifest" "$output_dir/data/manifest.json"
cp "${expected[0]}" "$output_dir/data/history.parquet"
for ((i=1; i<${#expected[@]}; i++)); do cp "${expected[i]}" "$output_dir/data/sprints/"; done
: > "$output_dir/.nojekyll"
: > "$output_dir/.sprint-intelligence-stage"
version="${GITHUB_SHA:-$(git rev-parse HEAD 2>/dev/null || echo local)}"
printf '%s\n' "$version" > "$output_dir/data/version.txt"
echo "Staged $manifest_count verified files (checksums only; semantic validation is Quick-side)"
