#!/bin/bash
# Installation des dépendances du plugin hikinterphone :
#  - venv Python propre au plugin (requests, aiohttp)
#  - SDK Hikvision HCNetSDK Linux (x86_64 ou aarch64), récupéré depuis le dépôt de
#    l'add-on Home Assistant pergolafabio/Hikvision-Addons (version figée)
PROGRESS_FILE=/tmp/jeedom/hikinterphone/dependency
if [ -n "$1" ]; then
    PROGRESS_FILE=$1
fi
BASEDIR=$(cd "$(dirname "$0")" && pwd)
VENV="$BASEDIR/venv"
SDKDIR="$BASEDIR/hiksdk"
# Version du SDK : 2e argument (choisi depuis la configuration du plugin) ou version figée livrée
SDK_COMMIT="$2"
if ! echo "$SDK_COMMIT" | grep -Eq '^[0-9a-f]{40}$'; then
    SDK_COMMIT=$(tr -d ' \n' < "$BASEDIR/sdk_commit")
fi
SDK_URL="https://raw.githubusercontent.com/pergolafabio/Hikvision-Addons/$SDK_COMMIT/hikvision-doorbell"

mkdir -p "$(dirname "$PROGRESS_FILE")"
touch "$PROGRESS_FILE"
echo 0 > "$PROGRESS_FILE"
echo "********************************************************"
echo "*             Installation des dépendances             *"
echo "********************************************************"
date

echo 5 > "$PROGRESS_FILE"
sudo apt-get update
echo 15 > "$PROGRESS_FILE"
sudo apt-get install -y python3 python3-venv python3-pip openssl curl ffmpeg

echo 25 > "$PROGRESS_FILE"
if [ ! -x "$VENV/bin/python3" ]; then
    python3 -m venv "$VENV"
fi
echo 35 > "$PROGRESS_FILE"
"$VENV/bin/python3" -m pip install --upgrade pip wheel
echo 45 > "$PROGRESS_FILE"
"$VENV/bin/python3" -m pip install --upgrade -r "$BASEDIR/requirements.txt"

# ---------------------------------------------------------------- SDK Hikvision
ARCH=$(uname -m)
case "$ARCH" in
    x86_64)  LIBDIR=lib-amd64 ;;
    aarch64) LIBDIR=lib-aarch64 ;;
    *) echo "Architecture $ARCH non supportée par le SDK Hikvision (x86_64 ou aarch64 uniquement)"; LIBDIR="" ;;
esac

if [ -n "$LIBDIR" ]; then
    echo "Téléchargement du SDK Hikvision ($LIBDIR)..."
    if [ "$LIBDIR" = "lib-amd64" ]; then
        FILES="libhcnetsdk.so libHCCore.so libhpr.so libcrypto.so libcrypto.so.1.0.0 libssl.so libz.so libNPQos.so libopenal.so.1 libAudioRender.so libPlayCtrl.so libSuperRender.so HCNetSDK_Log_Switch.xml"
    else
        FILES="libhcnetsdk.so libHCCore.so libhpr.so libcrypto.so libcrypto.so.1.1 libssl.so libssl.so.1.1 libz.so libAudioRender.so libPlayCtrl.so libSuperRender.so HCNetSDK_Log_Switch.xml"
    fi
    COM="libAudioIntercom.so libHCAlarm.so libHCCoreDevCfg.so libHCDisplay.so libHCGeneralCfgMgr.so libHCIndustry.so libHCPlayBack.so libHCPreview.so libHCVoiceTalk.so libStreamTransClient.so libSystemTransform.so libanalyzedata.so"
    [ "$LIBDIR" = "lib-amd64" ] && COM="$COM libiconv2.so" || COM="$COM libiconv.so.2"
    TMP="$SDKDIR.tmp"
    rm -rf "$TMP"
    mkdir -p "$TMP/HCNetSDKCom"
    OK=1
    N=0
    for f in $FILES; do
        curl -fsSL --retry 3 -o "$TMP/$f" "$SDK_URL/$LIBDIR/$f" || { echo "  absent : $f"; [ "$f" = "libhcnetsdk.so" ] && OK=0; }
        N=$((N+1)); echo $((50 + N)) > "$PROGRESS_FILE"
    done
    for f in $COM; do
        curl -fsSL --retry 3 -o "$TMP/HCNetSDKCom/$f" "$SDK_URL/$LIBDIR/HCNetSDKCom/$f" || echo "  absent : HCNetSDKCom/$f"
        N=$((N+1)); echo $((50 + N)) > "$PROGRESS_FILE"
    done
    if [ "$OK" = "1" ] && [ -s "$TMP/libhcnetsdk.so" ]; then
        rm -rf "$SDKDIR"
        mv "$TMP" "$SDKDIR"
        echo "SDK installé dans $SDKDIR"
    else
        rm -rf "$TMP"
        echo "ERREUR : téléchargement du SDK impossible (accès à raw.githubusercontent.com ?)"
    fi
fi

echo 90 > "$PROGRESS_FILE"
sudo chown -R www-data:www-data "$VENV" "$SDKDIR" 2>/dev/null
"$VENV/bin/python3" -c "import requests, aiohttp; print('requests', requests.__version__, '/ aiohttp', aiohttp.__version__)"
if [ -f "$SDKDIR/libhcnetsdk.so" ]; then
    cd "$SDKDIR" && LD_LIBRARY_PATH="$SDKDIR:$SDKDIR/HCNetSDKCom" "$VENV/bin/python3" -c "
import sys; sys.path.insert(0, '$BASEDIR/hikinterphoned')
import hiksdk; s = hiksdk.HikSDK('$SDKDIR'); print('SDK Hikvision OK'); s.cleanup()"
fi
# Trace des versions installées (lue par Jeedom pour l'état des dépendances et la page Librairies)
if [ -f "$SDKDIR/libhcnetsdk.so" ]; then
    echo "$SDK_COMMIT" > "$SDKDIR/.commit"
fi
"$VENV/bin/python3" - "$BASEDIR" <<'PYEOF'
import json, sys, datetime, importlib.metadata as m, os
base = sys.argv[1]
out = {"date": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), "python": {}}
for line in open(os.path.join(base, "requirements.txt")):
    name = line.split("#")[0].strip().split(">")[0].split("=")[0].split("<")[0].strip()
    if name:
        try:
            out["python"][name] = m.version(name)
        except m.PackageNotFoundError:
            out["python"][name] = None
try:
    out["sdk_commit"] = open(os.path.join(base, "hiksdk", ".commit")).read().strip()
except OSError:
    out["sdk_commit"] = None
out["rev"] = int(open(os.path.join(base, "deps_rev")).read().strip())
json.dump(out, open(os.path.join(base, "versions.json"), "w"), indent=1)
print("Versions installées :", json.dumps(out))
PYEOF
sudo chown www-data:www-data "$BASEDIR/versions.json" 2>/dev/null
echo 100 > "$PROGRESS_FILE"
echo "********************************************************"
echo "*             Installation terminée                    *"
echo "********************************************************"
rm -f "$PROGRESS_FILE"
