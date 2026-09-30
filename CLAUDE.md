# tunebox

## Committing

`save.bat` is the only way to commit — never run `git commit` or `git push` directly. From a terminal, `save.bat quick "message"` commits and pushes with no menu or prompts; `save.bat quick-commit "message"` commits without pushing. (Run it from PowerShell: `.\save.bat quick "message"`. Not from Git Bash, which cannot start a .bat from a path with spaces and puts its Unix `find` ahead of the Windows one the script uses.) `quick` never deploys to ele; deploying stays a manual `save.bat deploy`.

Never add Co-Authored-By, "Generated with Claude Code", or any other Claude/AI attribution to commit messages or PR descriptions.
