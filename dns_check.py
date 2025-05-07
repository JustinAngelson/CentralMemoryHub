import socket
import sys
import urllib.request
import json

def check_dns(hostname):
    """
    Check if a hostname resolves to an IP address.
    Returns True if it resolves, False otherwise.
    """
    try:
        print(f"Checking DNS resolution for: {hostname}")
        ip = socket.gethostbyname(hostname)
        print(f"Resolved to IP: {ip}")
        return True
    except socket.gaierror as e:
        print(f"DNS resolution failed: {e}")
        return False

def check_http(url):
    """
    Check if an HTTP URL is accessible.
    Returns the response code if successful, error message otherwise.
    """
    try:
        print(f"Checking HTTP accessibility for: {url}")
        response = urllib.request.urlopen(url)
        return f"HTTP Status: {response.status}"
    except Exception as e:
        return f"HTTP connection failed: {e}"

def get_replit_domain():
    """Get the current Replit domain for this project."""
    try:
        print("Attempting to get current Replit domain...")
        # Try to get from environment variables
        import os
        repl_slug = os.environ.get('REPL_SLUG')
        repl_owner = os.environ.get('REPL_OWNER')
        
        if repl_slug and repl_owner:
            domain = f"{repl_slug}.{repl_owner}.repl.co"
            print(f"Found Replit domain: {domain}")
            return domain
        else:
            print("Could not find REPL_SLUG or REPL_OWNER in environment variables")
            
            # Fallback: Try using the hostname from .replit file
            try:
                with open('.replit', 'r') as f:
                    for line in f:
                        if "run" in line and ".repl.co" in line:
                            parts = line.split()
                            for part in parts:
                                if ".repl.co" in part:
                                    domain = part.strip('"\'')
                                    print(f"Found domain in .replit file: {domain}")
                                    return domain
            except Exception as e:
                print(f"Error reading .replit file: {e}")
            
            # Last resort: Let user input the domain
            user_domain = "memory-vault-angelson.replit.app"  # This is from the user's previous message
            print(f"Using domain from previous message: {user_domain}")
            return user_domain
    except Exception as e:
        print(f"Error getting Replit domain: {e}")
        return None

if __name__ == "__main__":
    # Get the Replit domain
    replit_domain = get_replit_domain()
    
    # If no domain was found, exit
    if not replit_domain:
        print("No Replit domain found. Cannot perform checks.")
        sys.exit(1)
    
    # Check DNS resolution for main domain
    print("\n=== Checking Main Replit Domain ===")
    dns_result = check_dns(replit_domain)
    
    # If DNS resolves, check HTTP accessibility
    if dns_result:
        http_result = check_http(f"https://{replit_domain}/sys/health")
        print(http_result)
    
    # Also check the specific domain from the error message
    print("\n=== Checking Custom GPT Error Domain ===")
    error_domain = "a4bcd18d-c239-4cf3-b41c-6f743ef6fa20-00-32na6d6s4kheq.kirk.replit.dev"
    error_dns_result = check_dns(error_domain)
    
    # Print final summary
    print("\n=== Summary ===")
    print(f"Main Domain DNS Resolution: {'Success' if dns_result else 'Failed'}")
    print(f"Error Domain DNS Resolution: {'Success' if error_dns_result else 'Failed'}")
    print(f"Your Main Replit Domain: {replit_domain}")
    print(f"Custom GPT Error Domain: {error_domain}")
    
    print("\n=== Replit Domain Info ===")
    print("Replit domains should be publicly accessible by default.")
    print("If DNS resolution is failing, it could be due to:")
    print("1. The Replit project is set to private")
    print("2. DNS propagation hasn't completed")
    print("3. The domain has changed or is incorrect")
    
    print("\n=== Suggested Solutions ===")
    print("1. Check project visibility in Replit settings (make sure it's public)")
    print("2. Try deploying to get a stable domain")
    print("3. Consider using a tunneling service like ngrok as a temporary solution")