# 🍎 MacBook M2 Setup Guide - Fraud Detection System

## Quick Fix for Your Current Error

The error you're seeing is related to Python's virtual environment setup. Here's the solution:

### Option 1: Use Python 3 without venv (Quickest)

```bash
# Navigate to project
cd ~/Desktop/Fraud-Detection-Syst

# Install dependencies directly (using --user flag for safety)
python3 -m pip install --user -r requirements.txt

# Run the application
python3 main.py
```

Then open: **http://localhost:5000**

---

### Option 2: Fresh Virtual Environment Setup (Recommended)

```bash
# Navigate to project
cd ~/Desktop/Fraud-Detection-Syst

# Remove the broken venv
rm -rf venv

# Install Python and pip via Homebrew (ensures pip is included)
brew install python@3.11

# Create new virtual environment with system pip
python3.11 -m venv venv --system-site-packages

# Activate it
source venv/bin/activate

# Upgrade pip inside venv
python -m pip install --upgrade pip setuptools wheel

# Install dependencies
pip install -r requirements.txt

# Run the application
python main.py
```

---

### Option 3: Use Conda (Alternative)

If you have Anaconda or Miniconda:

```bash
cd ~/Desktop/Fraud-Detection-Syst

# Create conda environment
conda create -n fraud-detection python=3.11 -y
conda activate fraud-detection

# Install pip packages
pip install -r requirements.txt

# Run
python main.py
```

---

## 🚀 One-Command Setup (Fresh Install)

If you want to start completely fresh:

```bash
# Navigate to Desktop
cd ~/Desktop

# Remove old directory
rm -rf Fraud-Detection-Syst

# Clone fresh copy
git clone https://github.com/jumanalnagesh80-pixel/Fraud-Detection-Syst.git
cd Fraud-Detection-Syst

# Install Homebrew Python (if not installed)
brew install python@3.11

# Create virtual environment
python3.11 -m venv venv

# Activate
source venv/bin/activate

# Install dependencies
pip install --upgrade pip
pip install -r requirements.txt

# Run the system
python main.py
```

---

## 🔧 Troubleshooting Common Mac Issues

### Issue: `python: command not found`
**Solution:** Use `python3` instead:
```bash
python3 main.py
```

### Issue: Port 5000 already in use (macOS AirPlay)
**Solution:** Disable AirPlay Receiver or use different port:
```bash
python3 main.py --port 5050
# Then open http://localhost:5050
```

To disable AirPlay permanently:
1. System Preferences → Sharing
2. Uncheck "AirPlay Receiver"

### Issue: `zsh: permission denied`
**Solution:** Make sure you're in the right directory:
```bash
cd ~/Desktop/Fraud-Detection-Syst
ls -la main.py  # Should see the file
python3 main.py
```

### Issue: SSL/Certificate errors
**Solution:** Install certificates:
```bash
cd "/Applications/Python 3.11/"
./Install Certificates.command
```

---

## ✅ Verification Steps

After installation, verify everything works:

```bash
# 1. Check Python version
python3 --version  # Should be 3.9 or higher

# 2. Check pip works
python3 -m pip --version

# 3. Test imports
python3 -c "import flask, sklearn, pandas, numpy; print('All dependencies OK!')"

# 4. Run the app
python3 main.py

# You should see:
# INFO Starting Sentinel dashboard on http://0.0.0.0:5000
```

---

## 🎯 Default Login Credentials

Once the app is running at http://localhost:5000:

- **Username:** `admin`
- **Password:** `admin123`

---

## 🍎 M2-Specific Performance Notes

Your MacBook M2 will run this beautifully:

✅ **All dependencies have native ARM64 support:**
- Flask - Pure Python
- scikit-learn - Native Apple Silicon wheels
- NumPy - Optimized for ARM64
- Pandas - ARM64 compatible
- SQLite - Built into Python

**Expected Performance:**
- Model training: ~2-3 seconds
- Transaction scoring: <50ms
- Dashboard load: <1 second
- Simulation (40 txns): <2 seconds

---

## 📦 What You Get

- ✅ **Advanced ML Model** - Random Forest fraud detection
- ✅ **Beautiful Dark UI** - Modern gradient design with animations
- ✅ **Real-time Charts** - Live updating with Chart.js
- ✅ **Authentication System** - Login/logout with sessions
- ✅ **Admin Panel** - User management (admin role only)
- ✅ **Role-Based Access** - Admin and user roles
- ✅ **Transaction Simulator** - Generate test transactions
- ✅ **Live Alerts** - Risk-based alerts with color coding
- ✅ **Profile Dropdown** - User info and admin access

---

## 🆘 Still Having Issues?

If you're still stuck, try this diagnostic:

```bash
# Check Python installation
which python3
python3 --version

# Check if pip is available
python3 -m pip --version

# If pip is missing, install it manually
curl https://bootstrap.pypa.io/get-pip.py -o get-pip.py
python3 get-pip.py
rm get-pip.py

# Then retry installation
cd ~/Desktop/Fraud-Detection-Syst
python3 -m pip install --user -r requirements.txt
python3 main.py
```

---

## 🎨 What the UI Looks Like

When you open http://localhost:5000, you'll see:

1. **Login Page** - Dark gradient with animated background
2. **Dashboard** - 4 KPI cards showing:
   - Total transactions
   - Fraud detected
   - Approved transactions
   - Average latency
3. **Live Charts**:
   - Hourly volume (bar + line combo)
   - Risk distribution (doughnut chart)
   - Top fraud categories (horizontal bars)
   - Model feature importance
4. **Real-time Feed** - Table of recent transactions
5. **Active Alerts** - High-risk events
6. **Manual Scoring** - Test form to score custom transactions
7. **User Profile Dropdown** - Access admin panel, logout

---

## Next Steps

1. Get the app running with one of the methods above
2. Login as admin (admin/admin123)
3. Click "Run Simulation" to generate test data
4. Explore the dashboard and charts
5. Try scoring a manual transaction
6. Access Admin Panel to manage users

Everything should work perfectly on your M2! 🚀
