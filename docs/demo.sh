cd "$(dirname "$0")/.."; source docs/_say.sh; export PATH="$PWD/.venv/bin:$PATH"; clear
note "the bot's brain, driven the way a chat would drive it (no token needed)"
run "python docs/chat_sim.py"
