# h4xtor share

**Del alt mellem din Android-telefon og din PC – lynhurtigt, krypteret og helt uden sky.**

Filer, hele mapper, links og udklipsholder flyver direkte mellem dine enheder over
dit eget Wi-Fi – eller over Wi-Fi Direct, når der slet ingen router er. Ingen konto,
ingen upload til nogen server, ingen størrelsesgrænse.

| | Windows / macOS / Linux | Android |
|---|---|---|
| Parring med QR-kode (5 sek.) | Viser QR | Scanner QR |
| Parring med 6-cifret kode | ✓ | ✓ |
| Én parring = begge veje | ✓ | ✓ |
| Filer, alle typer, ingen grænse | ✓ | ✓ |
| Hele mapper (med undermapper) | ✓ | ✓ |
| Genoptag afbrudte overførsler | ✓ | ✓ |
| Live fart, procent og tid tilbage | ✓ | ✓ |
| Annullér undervejs | ✓ | ✓ |
| Links åbner direkte i browseren | ✓ | ✓ |
| Udklipsholder-synk begge veje | ✓ | ✓ (når appen er åben, via notifikation eller kvikfelt) |
| Wi-Fi Direct (uden router) | Kobler på telefonens gruppe | Starter gruppen |
| Automatisk enhedssøgning (mDNS + UDP) | ✓ | ✓ |
| Netværksscanning / manuel IP | ✓ | ✓ |
| "Del"-menuen | "Send til" i Stifinder | Androids Del-ark |
| Kører i baggrunden | Ikon ved uret | Baggrundstjeneste + notifikationer |
| Start automatisk | Med Windows | Når telefonen tænder |
| Lyst / mørkt tema | Følger Windows | Følger Android |
| Send til **alle enheder** på én gang | ✓ (også Chrome-udvidelsen) | ✓ (Del-arket) |
| Telefonens notifikationer på PC'en – svar og afvis | Side *Notifikationer* + Windows-besked | Til/fra og valg af apps (slået fra som standard) |
| SMS fra PC'en – læs og skriv | Side *SMS* | Til/fra (slået fra som standard) |
| Skærmbillede på forlangende | Knap under *Fjernbetjening* | Du godkender på telefonen |
| Find min telefon (ringer højt, også på lydløs) | Knap under *Fjernbetjening* | Stop på telefonen eller fra PC'en |
| Fjernbetjening: lydstyrke, læs tekst højt, baggrundsbillede | ✓ | Til/fra |
| Google Drive (valgfri, slået fra) | *Indstillinger → Sky* | – |

## Kom i gang

1. **Hent** den nyeste udgave under [Releases](https://github.com/h4xtor/h4xtor-share/releases):
   `h4xtor-share-windows.exe` til PC'en og `h4xtor-share-android.apk` til telefonen.
2. **Start** begge. Er de på samme Wi-Fi, dukker de op hos hinanden af sig selv.
3. **Forbind**: Klik **Forbind ny enhed** på PC'en, tryk **Scan QR-kode** på telefonen. Færdig.

Derefter:

- **PC → telefon:** træk filer ind i vinduet, eller højreklik på en fil → *Send til* → *h4xtor-share*.
- **Telefon → PC:** tryk *Del* i en hvilken som helst app og vælg *h4xtor share* – eller brug knapperne i appen.
- **Links:** del et link fra telefonen, så åbner det i PC'ens browser med det samme (og omvendt).
- **Udklipsholder:** kopiér på den ene – sæt ind på den anden.

### Wi-Fi Direct – når der ikke er nogen router

1. Tryk **Start Wi-Fi Direct** i appen på telefonen.
2. Er PC'en allerede parret, så tryk **Forbind <din PC> automatisk** – PC'en spørger og kobler selv på.
   Ellers: skriv netværksnavn og kode under *Indstillinger → Wi-Fi Direct* på PC'en.
3. Del som normalt – direkte mellem enhederne, uden internet.

Mens PC'en er på telefonens Wi-Fi Direct-netværk, har den normalt ikke internet via
Wi-Fi. Knappen **Tilbage til <dit Wi-Fi>** skifter tilbage med ét klik.

## Sikkerhed

- Hver enhed har sit eget RSA-certifikat. Al trafik er TLS-krypteret.
- Ved parring låses forbindelsen til den anden enheds certifikat-fingeraftryk
  ("pinning"). Et ændret certifikat afvises.
- QR-koden indeholder fingeraftrykket og en engangskode, der udløber efter få minutter,
  så forbindelsen er låst fra allerførste byte.
- Den 6-cifrede kode udløber efter 2 minutter.
- Modtagne filnavne renses (ingen `../`, ingen reserverede Windows-navne), og eksisterende
  filer overskrives aldrig.
- Kun `http(s)`-links kan åbnes automatisk.

## Teknik i korte træk

- **Desktop:** Python 3.11+, aiohttp (TLS-server og -klient), zeroconf (mDNS), Tk med et
  eget lille komponent-bibliotek (`ui_kit.py`), pystray til bakke-ikonet på Windows.
- **Android:** Java uden tunge frameworks. En forgrundstjeneste (`ShareService`) ejer
  server, søgning, overførsler og notifikationer; aktiviteterne er tynde visninger.
  QR-scanning via Google Code Scanner (kræver ingen kamera-tilladelse), QR-visning via ZXing.
- **Protokol:** HTTPS/JSON på port 47474 (TCP), UDP-annoncering på 47474, mDNS-tjenesten
  `_h4xtor-share._tcp`. Filer streames i 1 MB-bidder direkte til disk.

### Protokol (v1)

| Endpoint | Formål |
|---|---|
| `GET /api/v1/info`, `GET /api/v1/ping` | Identitet, kapabiliteter, liveness |
| `POST /api/v1/pair/request` + `/pair/confirm` | Parring med 6-cifret kode (`reverse` gør den gensidig) |
| `POST /api/v1/pair/qr` | Øjeblikkelig parring med engangskoden fra QR |
| `POST /api/v1/unpair` | Glem hinanden |
| `POST /api/v1/clipboard` | Tekst til udklipsholderen |
| `POST /api/v1/link` | Link der åbnes i browseren |
| `POST /api/v1/files/init` + `PUT /api/v1/files/<id>` | Fil med genoptagelse (`X-H4xtor-Offset`) |
| `POST /api/v1/folders/init` + `PUT .../<folder>/<file>` + `POST /folders/complete` | Mappe |
| `POST /api/v1/wifi-direct/offer` | Telefonen tilbyder PC'en sin Wi-Fi Direct-gruppe |
| `POST /api/v1/notification`, `/sms/incoming` | Telefon → PC: notifikationer og nye SMS |
| `POST /api/v1/notification/action`, `/sms/threads`, `/sms/messages`, `/sms/send` | PC → telefon: svar/afvis, læs og send SMS |
| `POST /api/v1/screenshot`, `/find`, `/remote/volume`, `/remote/speak`, `PUT /remote/wallpaper` | PC → telefon: skærmbillede, find telefon, fjernbetjening |

Nye funktioner annonceres som *capabilities*, så ældre versioner aldrig bliver kaldt med dem.
Detaljer: [docs/protocol-v1.2.md](docs/protocol-v1.2.md).

QR-format: `h4xtor://pair?v=1&id=…&n=…&fp=…&p=…&a=ip1,ip2&s=…&pl=…`

## Byg selv

```bash
# Desktop
python -m pip install -e ".[dev]"
pytest
python -m h4xtor_share                     # start appen
python -m PyInstaller --clean --noconfirm packaging/h4xtor-share.spec   # .exe

# Android (JDK 17 + Android SDK)
gradle -p android testDebugUnitTest lintDebug assembleDebug
```

GitHub Actions tester på Windows, macOS og Linux, bygger `.exe`, macOS- og Linux-binærer
samt APK'en ved hvert push. Et `v*`-tag laver en release med alle filer.

## Ærlige begrænsninger

- **Bluetooth-overførsel** er ikke med: Wi-Fi Direct er 10–50× hurtigere og dækker det
  samme behov ("ingen router").
- Android tillader kun apps at læse udklipsholderen, når de er i forgrunden. Derfor
  synkroniseres telefonens udklipsholder, når appen åbnes, via notifikationsknappen eller
  via kvikfeltet *Send udklip*. Den anden vej (PC → telefon) virker altid.
- macOS har ingen offentlig Wi-Fi Direct-API; en Mac kan dog koble på telefonens gruppe
  som almindeligt Wi-Fi.
- **Notifikationer, SMS og fjernbetjening kræver, at telefonen og PC'en er på samme netværk**
  (eller Wi-Fi Direct). Der er ingen sky-relæ som i Join – det er bevidst.
- **Skærmbillede på forlangende:** Android 14 og nyere kræver, at du godkender skærmoptagelse
  på telefonen *hver gang*. Det kan ingen app komme udenom. Kan appen ikke vise spørgsmålet
  med det samme, kommer der en notifikation, du skal trykke på.
- **Svar på notifikationer** virker kun, når appen selv tilbyder et svarfelt i notifikationen
  (fx beskeder). Andre notifikationer kan kun vises og afvises.
- **SMS** bruger telefonens egen SMS-funktion og dit abonnement. MMS (billeder i SMS) vises ikke.
- **Find min telefon** ringer via alarm-lyden. Står telefonen på *Forstyr ikke* med alarmer
  slået fra, kan den kun vibrere.
- **Google Drive** er kun forberedt: du kan forbinde og teste forbindelsen, men delingen bruger
  den ikke endnu. Du skal selv oprette et OAuth-klient-ID i Google Cloud Console.
