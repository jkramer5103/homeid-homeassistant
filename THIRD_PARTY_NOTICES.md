This integration bundles the `homeid` client from
[homeid-python](https://github.com/jkramer5103/homeid-python) in
`custom_components/homeid_airfryer/homeid` (commit recorded in its `SOURCE` file).

Protocol primitives in `custom_components/homeid_airfryer/homeid/_vendor` are redistributed from
[Renaud Allard's Philips HomeID integration](https://github.com/renaudallard/homeassistant_philips_homeid)
at commit `f8071b5a3a6ccb66cf0d94ba554758d6f1ff5bd0` under the BSD 2-Clause
license. The copyright headers and complete license are retained in that directory
and included in distributions. These modules do not depend on Home Assistant.

Local modifications: `local_models.py` adds the APK's two-byte random prefix
when encrypting AES payloads and strips it on decryption. It also accepts valid
unprefixed JSON responses for compatibility. These changes were verified against
`Crypto.java` and `ByteUtil.java` in the locally extracted 7.10.0 APK.
`mqtt_api.py` stamps status-port observations with a revision and receive time,
so shadow/metadata updates cannot make cached cooking status look fresh.
Its air-purifier detector returns false to remove a deferred import of Home
Assistant entity descriptions; the public facade only accepts SPECTRE fryers.

The public client and the Home Assistant integration are additions by the
homeid-python and homeid-homeassistant projects. Protocol research also consulted
[b12e's integration](https://github.com/b12e/hacs_philips_airfryer); its code is not
redistributed.

Android APKs and decompiled proprietary source are local research artifacts only,
excluded from Git and Python distributions.
