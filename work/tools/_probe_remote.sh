hostname
nproc
free -g | head -3
echo "--- home"
ls -d /home/lab/zhangmx 2>/dev/null || ls -d /home/*/ 2>/dev/null | head -5
echo "--- comsol"
ls -d /usr/local/comsol* /opt/comsol* /home/*/comsol* 2>/dev/null | head -5
find /usr/local /opt /home -maxdepth 4 -name comsolbatch -type f 2>/dev/null | head -3
echo "--- python"
python3 -c "import sys; print(sys.version.split()[0])" 2>/dev/null || echo "no python3"
echo "--- disk"
df -h /home | tail -1
