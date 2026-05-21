# 🚀 QUICK FIX - MacBook M2 Error Resolution

## Your Error:
```
Error: Command '[...python3.11', '-m', 'ensurepip', '--upgrade', '--default-pip']' 
returned non-zero exit status 1.
```

## The Problem:
Your Python 3.11 installation doesn't have `pip` properly configured, which breaks `venv` creation.

---

## ✅ SOLUTION 1: Simplest Way (No venv needed)

Just run it directly with Python 3:

```bash
cd ~/Desktop/Fraud-Detection-Syst

# Install dependencies to your user directory
python3 -m pip install --user --upgrade pip
python3 -m pip install --user -r requirements.txt

# Run the app
python3 main.py
```

Open: **http://localhost:5000**
Login: **admin** / **admin123**

**That's it!** No virtual environment needed for testing.

---

## ✅ SOLUTION 2: Use the Setup Script (Recommended)

We've created an automated setup script:

```bash
cd ~/Desktop/Fraud-Detection-Syst

# Run the setup script
bash setup_mac.sh

# Then start the app
source venv/bin/activate
python main.py
```

---

## ✅ SOLUTION 3: Fix Your Python Installation

Install Python properly via Homebrew:

```bash
# Install/reinstall Python 3.11 with pip included
brew install python@3.11

# Verify pip works
python3.11 -m pip --version

# Now create venv
cd ~/Desktop/Fraud-Detection-Syst
rm -rf venv
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python main.py
```

---

## 🎯 Quick Commands Reference

### Start the app (if already installed):
```bash
cd ~/Desktop/Fraud-Detection-Syst
source venv/bin/activate  # If using venv
python main.py
```

### Change port (if 5000 is busy):
```bash
python main.py --port 5050
# Then open http://localhost:5050
```

### Check if it's running:
```bash
# You should see output like:
# INFO Starting Sentinel dashboard on http://0.0.0.0:5000
```

---

## 🆘 Still Not Working?

Try the nuclear option - fresh install with system Python:

```bash
cd ~/Desktop
rm -rf Fraud-Detection-Syst
git clone https://github.com/jumanalnagesh80-pixel/Fraud-Detection-Syst.git
cd Fraud-Detection-Syst

# Install directly without venv
python3 -m pip install --user -r requirements.txt

# Run
python3 main.py
```

---

## ✅ What You Should See

When running successfully, you'll see:

```
INFO Training fraud detection model on synthetic data...
INFO Model trained | accuracy=0.XXX precision=0.XXX recall=0.XXX
INFO Starting Sentinel dashboard on http://0.0.0.0:5000
```

Then you can open your browser to **http://localhost:5000** and see the beautiful dashboard! 🎨

---

## 📌 Key Points for M2 Mac

1. ✅ **Always use `python3`** (not just `python`)
2. ✅ **Port 5000 conflicts with AirPlay** - use `--port 5050` if needed
3. ✅ **All dependencies work natively on M2** - no Rosetta needed
4. ✅ **Virtual env is optional** - you can run directly with `python3`

---

Pick **Solution 1** if you just want to test it quickly!
Pick **Solution 2** if you want a proper setup!
Pick **Solution 3** if you want to fix Python for the long term!
