DSC Bridge — Windows Setup
===========================

This package lets you sign Frappe documents with your HYP2003 DSC USB token.

What you should have received
-----------------------------
1. dsc-bridge.exe          (the bridge program)
2. dsc-bridge.json         (config — already points to HYP2003 driver paths)
3. start-dsc-bridge.bat    (double-click this to start the bridge)
4. README-windows.txt      (this file)

One-time setup (5 minutes)
--------------------------
1. Install your HYP2003 token's driver software (the CD that came with the
   token, or your CA's downloads page — eMudhra / Sify / Capricorn / etc.).
   After install you should be able to plug in the token and see your name
   in the vendor's "Token Manager" utility.

2. Copy all four files (dsc-bridge.exe, dsc-bridge.json, start-dsc-bridge.bat,
   this README) into a folder of your choice, for example:
       C:\Users\<you>\dsc-bridge\

3. Plug in your HYP2003 token.

4. Double-click start-dsc-bridge.bat.
   Windows may show "Windows protected your PC" — click "More info" then
   "Run anyway". This happens because the .exe is not yet code-signed.

5. A black command window opens and stays open. That's normal — leave it open
   while you sign. To stop the bridge later, press Ctrl+C in that window or
   just close it.

6. Verify the bridge is alive: open this URL in your browser:
       https://127.0.0.1:4645/v1/status
   Browser will warn about a self-signed certificate — click "Advanced" then
   "Proceed". You should see a JSON page mentioning your token's certificate.

Pair the bridge with the Frappe site (one-time per laptop)
----------------------------------------------------------
1. On the Frappe site (open in your browser), go to:
       DSC Agent Registration  →  New
   Fill in your user, give the device a name (e.g. "Office Laptop"), Save.

2. Click "Generate Pairing Code" — a 6-digit code appears. Copy it.

3. On the same Windows laptop, in a NEW browser tab, click the
   "Connect Agent" button on that page. A pop-up will ask for the pairing
   code — paste the 6 digits.

4. The page should say "Paired successfully". You won't need to pair again
   on this laptop — the pairing is stored in Windows Credential Manager.

Signing a document
------------------
1. Make sure start-dsc-bridge.bat is running (black window open).
2. Make sure your HYP2003 token is plugged in.
3. Open a DSC Signing Request in the Frappe site.
4. Click "Sign Now". Allow geolocation if asked.
5. The bridge will pop up a PIN dialog — enter your token PIN.
6. Done — the signed PDF is attached to the request.

Troubleshooting
---------------
"Cannot connect to bridge"
    The bat window is closed. Re-run start-dsc-bridge.bat.

"No token detected"
    Unplug the token, plug it back in. If still nothing, open the vendor's
    Token Manager utility to confirm Windows itself sees the token.

"PKCS#11 library not found"
    The driver is in a non-standard location. Open dsc-bridge.json and
    add the actual path to the eps2003csp11.dll file. To find it:
        Start  →  search "Edit the system environment variables"  →  Path
    Or search C:\ for "eps2003csp11.dll".

"Sign failed: certificate mismatch"
    The token presents a different certificate from the one registered in
    the DSC Profile. Ask your admin to re-register the certificate.

Need help: contact your DSC administrator.
