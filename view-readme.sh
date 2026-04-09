#!/bin/bash

# Enhanced README viewer with ANSI color support
# Usage: ./view-readme.sh [--color|--no-color]

# ANSI color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
WHITE='\033[1;37m'
BOLD='\033[1m'
NC='\033[0m' # No Color

# Check if colors should be enabled
USE_COLOR=true
if [[ "$1" == "--no-color" ]] || [[ ! -t 1 ]]; then
    USE_COLOR=false
fi

color_text() {
    local color=$1
    local text=$2
    if [[ "$USE_COLOR" == "true" ]]; then
        echo -e "${color}${text}${NC}"
    else
        echo "$text"
    fi
}

# Enhanced README display with colors
display_colored_readme() {
    local readme_file="${1:-README.md}"

    if [[ ! -f "$readme_file" ]]; then
        color_text "$RED" "[!] README.md not found in current directory"
        exit 1
    fi

    echo
    color_text "$CYAN" "====================================="
    color_text "$BOLD$WHITE" "    Copilot API Proxy v2.0 README    "
    color_text "$CYAN" "====================================="
    echo

    while IFS= read -r line; do
        # Headers
        if [[ $line =~ ^#[[:space:]]*\[.*\] ]]; then
            color_text "$BOLD$YELLOW" "$line"
        elif [[ $line =~ ^#[[:space:]] ]]; then
            color_text "$BOLD$WHITE" "$line"

        # Section markers in brackets
        elif [[ $line =~ \[CFG\] ]]; then
            echo "${line/\[CFG\]/${PURPLE}[CFG]${NC}}"
        elif [[ $line =~ \[LOCK\] ]]; then
            echo "${line//\[LOCK\]/${RED}[LOCK]${NC}/}"
        elif [[ $line =~ \[PERF\] ]]; then
            echo "${line///}" | sed "s/\[PERF\]/${GREEN}[PERF]${NC}/g"
        elif [[ $line =~ \[API\] ]]; then
            echo "${line///}" | sed "s/\[API\]/${BLUE}[API]${NC}/g"
        elif [[ $line =~ \[\+\] ]]; then
            echo "${line///}" | sed "s/\[+\]/${GREEN}[+]${NC}/g"
        elif [[ $line =~ \[\!\] ]]; then
            echo "${line///}" | sed "s/\[!\]/${YELLOW}[!]${NC}/g"
        elif [[ $line =~ \[\*\] ]]; then
            echo "${line///}" | sed "s/\[*\]/${CYAN}[*]${NC}/g"
        elif [[ $line =~ \[\>\>\] ]]; then
            echo "${line///}" | sed "s/\[>>\]/${BOLD}${GREEN}[>>]${NC}/g"

        # Code blocks
        elif [[ $line =~ ^\`\`\` ]]; then
            color_text "$PURPLE" "$line"

        # URLs and links
        elif [[ $line =~ https?:// ]]; then
            echo "$line" | sed -E "s|(https?://[^[:space:]]+)|${BLUE}\1${NC}|g"

        # File paths
        elif [[ $line =~ /[a-zA-Z0-9/_.-]+ ]]; then
            echo "$line" | sed -E "s|(/[a-zA-Z0-9/_.-]+)|${CYAN}\1${NC}|g"

        # Commands starting with sudo, systemctl, etc.
        elif [[ $line =~ ^[[:space:]]*(sudo|systemctl|curl|git|make|python|cd)[[:space:]] ]]; then
            color_text "$GREEN" "$line"

        # Regular text
        else
            echo "$line"
        fi
    done < "$readme_file"

    echo
    color_text "$CYAN" "====================================="
    color_text "$WHITE" "Use: cat README.md | less -R for paging"
    color_text "$CYAN" "====================================="
}

# Main execution
main() {
    local readme_path="$(dirname "$0")/README.md"

    if [[ "$1" == "--help" ]] || [[ "$1" == "-h" ]]; then
        echo "Enhanced README viewer with terminal colors"
        echo
        echo "Usage: $0 [OPTIONS]"
        echo
        echo "Options:"
        echo "  --color      Force enable colors (default if TTY)"
        echo "  --no-color   Disable colors"
        echo "  --help, -h   Show this help"
        echo
        echo "Features:"
        echo "  - Color-coded section headers"
        echo "  - Syntax highlighting for commands"
        echo "  - URL highlighting"
        echo "  - Status indicators ([+], [!], [*], etc.)"
        exit 0
    fi

    display_colored_readme "$readme_path"
}

main "$@"