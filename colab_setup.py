# Helper to set env vars in a Colab Python cell
import os

def set_env(supabase_url: str, supabase_key: str, headless: str = "true"):
    os.environ["SUPABASE_URL"] = supabase_url
    os.environ["SUPABASE_KEY"] = supabase_key
    os.environ["HEADLESS"] = headless
    print("Environment variables set: SUPABASE_URL, SUPABASE_KEY, HEADLESS")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--key", required=True)
    parser.add_argument("--headless", default="true")
    args = parser.parse_args()
    set_env(args.url, args.key, args.headless)
