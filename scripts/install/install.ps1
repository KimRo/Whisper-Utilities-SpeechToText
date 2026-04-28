# Upgrading pip
python -m pip install --upgrade pip

# Install numpy separately with verbose output
target = 'numpy'
try:
    import subprocess
    subprocess.check_call(["pip", "install", target, '--verbose'])
except subprocess.CalledProcessError as e:
    print(f'Error during installation of {target}: {e}')  
    exit(1)

# Install PyTorch
# (Assumed existing code follows here)