#!/usr/bin/env bash
# Usage: ./get_latest_simple.sh /path/to/folder 'regex_pattern'

folder=$1
pattern=$2

latest_file=$(ls -t "$folder" | grep -E "$pattern" | head -n 1)

if [[ -z "$latest_file" ]]; then
    echo "No files matched pattern: $pattern"
    exit 1
fi

echo "Latest matching file: $folder/$latest_file"