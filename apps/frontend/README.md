# Frontend Test Console

This is a lightweight static UI for exercising the Django research API without Postman.

## Run locally
1. Start the backend and worker (see `apps/backend/README.md`).
2. Serve this folder:
   ```bash
   python -m http.server 5173
   ```
3. Open `http://127.0.0.1:5173/` in your browser.
4. Confirm the API Base URL matches your backend (default `http://127.0.0.1:8000/api/research`).
5. Use Start/Upload/Continue/Detail/History to test the endpoints.

## Notes
- Upload accepts `.txt` and `.pdf` (field name `file`).
- If you hit CORS errors, set `CORS_ALLOW_ALL=true` in `apps/backend/.env` or add your origin to `CORS_ALLOWED_ORIGINS`.
