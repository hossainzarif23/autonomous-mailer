from __future__ import annotations

import uvicorn


def main() -> None:
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        loop="app.uvicorn_loop:selector_loop_factory",
    )


if __name__ == "__main__":
    main()
