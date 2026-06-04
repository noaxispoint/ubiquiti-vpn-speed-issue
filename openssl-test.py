import subprocess
import time
import os

def test_openssl_aes():
    """Test AES throughput using openssl speed"""
    result = subprocess.run(
        ["openssl", "speed", "-evp", "aes-256-gcm"],
        capture_output=True, text=True
    )
    return result.stdout + result.stderr

def check_crypto_drivers():
    """Check which crypto drivers kernel is using"""
    with open("/proc/crypto", "r") as f:
        return f.read()

if __name__ == "__main__":
    print("=== Kernel Crypto Drivers ===")
    crypto = check_crypto_drivers()
    for line in crypto.split("\n"):
        if any(x in line.lower() for x in ["aes", "ghash", "pmull", "driver", "module"]):
            print(line)
    
    print("\n=== OpenSSL AES-256-GCM Benchmark ===")
    print(test_openssl_aes())
