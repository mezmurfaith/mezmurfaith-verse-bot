#!/bin/zsh
# Makes one real AI poster on this Mac without posting anything.
# Your OpenAI key is typed hidden, used once, and never saved.
cd "$(dirname "$0")/.." || exit 1
read -s "key?Paste your OpenAI key, then press Enter (it stays hidden): "
echo
echo "Making the poster (about 30-60 seconds)..."
if OPENAI_API_KEY="$key" .venv/bin/python -m bot.main render; then
  echo
  echo "Done! The poster is in the output folder."
else
  echo
  echo "It didn't work. Tell Claude what the message above says."
fi
unset key
