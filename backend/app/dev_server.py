from __future__ import annotations

import os

import uvicorn


def main() -> None:
    port = int(os.environ.get("API_PORT", "8000"))
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=port,
        reload=True,
        loop="app.uvicorn_loop:selector_loop_factory",
    )


if __name__ == "__main__":
    main()
