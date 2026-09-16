# Deploy FocusX on PythonAnywhere (SQLite)

SQLite is stored in `focusx.db` beside the app source and remains available
between reloads on PythonAnywhere. It is suitable for a small number of users.

1. Upload this `focusx` directory to `/home/YOUR_USERNAME/focusx` using the
   Files tab or clone your Git repository in a Bash console.
2. In a Bash console, create and activate a virtual environment, then install
   the app requirements:

   ```bash
   mkvirtualenv --python=/usr/bin/python3.13 focusx-env
   cd ~/focusx
   pip install -r requirements.txt
   ```

3. On the **Web** tab, choose **Add a new web app** > **Manual configuration**
   and select the same Python version. Set its virtualenv to
   `/home/YOUR_USERNAME/.virtualenvs/focusx-env`.
4. Open the WSGI configuration file linked on the Web tab. Copy the contents
   of `pythonanywhere_wsgi.py` into it, replacing `YOUR_USERNAME` and the
   secret placeholder. Generate a long random secret; never commit it.
5. Click **Reload** on the Web tab and visit
   `https://YOUR_USERNAME.pythonanywhere.com`.

After the first visit, FocusX creates its SQLite database automatically. Back
it up periodically from a Bash console:

```bash
cp ~/focusx/focusx.db ~/focusx/backups/focusx-$(date +%F).db
```

Do not run `python app.py` to serve the public site; PythonAnywhere loads the
Flask app through its WSGI configuration.
