# r4_sup.sh TEAM ...: see r4_supervise.sh. Kept short: old supervisors read on past their end offset.
exec bash "$(dirname "$0")/r4_supervise.sh" "$@"
