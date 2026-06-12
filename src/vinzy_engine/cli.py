"""Typer CLI for Vinzy-Engine."""

import typer
from rich.console import Console

app = typer.Typer(name="vinzy", help="Vinzy-Engine: License key generator and manager")
console = Console()


@app.command()
def serve(
    host: str = typer.Option("0.0.0.0", help="Bind host"),
    port: int = typer.Option(8080, help="Bind port"),
):
    """Start the Vinzy-Engine API server."""
    import uvicorn
    from vinzy_engine.app import create_app

    console.print(f"[bold green]Starting Vinzy-Engine on {host}:{port}[/bold green]")
    uvicorn.run(create_app(), host=host, port=port)


@app.command()
def generate(
    product: str = typer.Argument(..., help="3-char product prefix (e.g., ZUL)"),
):
    """Generate a license key (offline, no DB required)."""
    from vinzy_engine.common.config import get_settings
    from vinzy_engine.keygen.generator import generate_key

    settings = get_settings()
    key = generate_key(
        product,
        settings.current_hmac_key,
        version=settings.current_hmac_version,
    )
    console.print(f"[bold]{key}[/bold]")


@app.command()
def validate(
    key: str = typer.Argument(..., help="License key to validate"),
):
    """Validate a license key offline (HMAC check only)."""
    from vinzy_engine.common.config import get_settings
    from vinzy_engine.keygen.validator import validate_key_multi

    settings = get_settings()
    result = validate_key_multi(key, settings.hmac_keyring)

    if result.valid:
        console.print(f"[bold green]VALID[/bold green] — {result.message}")
        console.print(f"  Product: {result.product_prefix}")
    else:
        console.print(f"[bold red]{result.code}[/bold red] — {result.message}")
        raise typer.Exit(1)


@app.command()
def health(
    url: str = typer.Option("http://localhost:8080", help="Server URL"),
):
    """Check Vinzy-Engine server health."""
    import httpx

    try:
        resp = httpx.get(f"{url}/health", timeout=5)
        data = resp.json()
        console.print(f"[bold green]{data['status']}[/bold green] — v{data['version']}")
    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
