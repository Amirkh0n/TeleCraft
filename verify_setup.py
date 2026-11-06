#!/usr/bin/env python3
"""
TeleCraft Setup Verification Script
Check if all components are properly installed and configured
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))


def check_python_version():
    """Check Python version"""
    print("Checking Python version...")
    version = sys.version_info
    if version.major >= 3 and version.minor >= 11:
        print(f"[OK] Python {version.major}.{version.minor}.{version.micro} found")
        return True
    else:
        print(f"[FAIL] Python 3.11+ required, found {version.major}.{version.minor}.{version.micro}")
        return False


def check_virtual_env():
    """Check if virtual environment is active"""
    print("\nChecking virtual environment...")
    in_venv = hasattr(sys, 'real_prefix') or (
        hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix
    )
    if in_venv:
        print(f"[OK] Virtual environment is active: {sys.prefix}")
        return True
    else:
        print("[WARN] Virtual environment not active")
        print("   Run: source venv/bin/activate (Linux/Mac)")
        print("   Run: venv\\Scripts\\activate.bat (Windows)")
        return False


def check_python_packages():
    """Check if required packages are installed"""
    print("\nChecking Python packages...")
    required_packages = [
        'fastapi',
        'uvicorn',
        'python-telegram-bot',
        'sqlalchemy',
        'aiosqlite',
        'pydantic',
        'pydantic_settings',
        'python-dotenv',
        'prometheus_client'
    ]
    
    missing = []
    for package in required_packages:
        try:
            __import__(package)
            print(f"[OK] {package}")
        except ImportError:
            print(f"[MISSING] {package}")
            missing.append(package)
    
    if missing:
        print(f"\n[WARN] Missing packages: {', '.join(missing)}")
        print("   Run: pip install -r requirements.txt")
        return False
    return True


def check_env_file():
    """Check if .env file exists and is configured"""
    print("\nChecking environment configuration...")
    
    env_file = project_root / '.env'
    
    if not env_file.exists():
        print("[WARN] .env file not found")
        print("   Run: cp .env.example .env")
        print("   Edit .env and add TELEGRAM_TOKEN")
        return False
    
    print(f"[OK] .env file exists: {env_file}")
    
    # Check if TELEGRAM_TOKEN is set
    with open(env_file) as f:
        content = f.read()
        if 'TELEGRAM_TOKEN=' in content and 'your_' not in content and 'token_here' not in content:
            print("[OK] TELEGRAM_TOKEN is configured")
            return True
        else:
            print("[WARN] TELEGRAM_TOKEN not properly configured")
            print("   Edit .env and add your TELEGRAM_TOKEN")
            return False


def check_database():
    """Check if database can be initialized"""
    print("\nChecking database...")
    try:
        from core.database import init_models
        import asyncio
        
        async def check_db():
            await init_models()
            return True
        
        result = asyncio.run(check_db())
        if result:
            print("[OK] Database initialized successfully")
            return True
    except Exception as e:
        print(f"[FAIL] Database initialization failed: {e}")
        return False


def check_directories():
    """Check if necessary directories exist"""
    print("\nChecking directories...")
    required_dirs = ['data', 'logs']
    all_exist = True
    
    for dirname in required_dirs:
        dirpath = project_root / dirname
        if dirpath.exists() and dirpath.is_dir():
            print(f"[OK] {dirname}/")
        else:
            print(f"[WARN] {dirname}/ - not found, will be created")
            dirpath.mkdir(exist_ok=True)
    
    return all_exist


def check_imports():
    """Check if core modules can be imported"""
    print("\nChecking module imports...")
    modules = [
        'constructor.bot',
        'constructor.handlers',
        'constructor.flows.bots',
        'engine.router',
        'engine.actions',
        'core.config',
        'core.logger',
        'core.database',
        'core.errors',
        'core.validators',
        'app.main'
    ]
    
    all_ok = True
    for module in modules:
        try:
            __import__(module)
            print(f"[OK] {module}")
        except ImportError as e:
            print(f"[FAIL] {module} - {e}")
            all_ok = False
    
    return all_ok


def main():
    """Run all checks"""
    print("="*60)
    print("TeleCraft Setup Verification")
    print("="*60)
    
    results = {
        'Python Version': check_python_version(),
        'Virtual Environment': check_virtual_env(),
        'Python Packages': check_python_packages(),
        'Environment File': check_env_file(),
        'Database': check_database(),
        'Directories': check_directories(),
        'Module Imports': check_imports()
    }
    
    print("\n" + "="*60)
    print("Verification Summary")
    print("="*60)
    
    for check, result in results.items():
        status = "[OK]" if result else "[FAIL]"
        print(f"{status} - {check}")
    
    all_passed = all(results.values())
    
    print("\n" + "="*60)
    if all_passed:
        print("[OK] All checks passed!")
        print("\nYou can now run TeleCraft:")
        print("  Terminal 1: python start.py")
        print("  Terminal 2: python webhook_start.py")
    else:
        print("[FAIL] Some checks failed")
        print("\nPlease fix the issues above before running TeleCraft")
    print("="*60)
    
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
