Open the session history GUI and automatically show the diff for the most recent change in the current project. Run this exact bash command:

```
nohup CLAUDEHIST_VENV_PLACEHOLDER/bin/python CLAUDEHIST_DIR_PLACEHOLDER/review_gui.py --last "$(pwd)" > /dev/null 2>&1 &
```

Do not wait for it to finish. Just confirm it was launched.
