# Opdateringslog

Appen læser denne fil, så formatet er fast:
`## <version> – <ÅÅÅÅ-MM-DD>`, derefter `### Nyt`, `### Forbedret` og `### Rettet` med punkter, der starter med `- `.
Nyeste version øverst. Udgivelsen fejler, hvis versionen mangler her.

## 1.3.8 – 2026-10-22
### Rettet
- En fil sendt fra telefonen til PC'en kunne hænge i appen. Over Bluetooth hoppede bjælken til næsten 100 % og stod så stille i flere minutter – nu sendes filen i små bidder, så bjælken viser, hvor langt den reelt er, og arket lukker selv, når filen er fremme.
- Telefonen sendte den samme fil igen, når appen blev åbnet på ny (fx efter en opdatering, eller når Android genskabte "Del"-arket). Nu sendes en deling præcis én gang.
- PC'en skiftede tilbage til Wi-Fi midt i en Bluetooth-overførsel og afbrød den. Nu venter den, til filen er fremme.
- Hvis afsenderen ikke nåede at få "modtaget"-svaret og prøvede igen, blev filen gemt to gange. Nu genkender både PC og telefon filen og gemmer den kun én gang.
### Forbedret
- En overførsel, der går helt i stå (fx hvis Wi-Fi forsvinder), stopper nu efter 45 sekunder med en tydelig besked i stedet for at hænge i op til et kvarter. Tryk "Fortsæt" for at fortsætte, hvor den slap.
- "Fortsæt" på en afbrudt overførsel bruger nu den vej til PC'en, der virker lige nu (Wi-Fi eller Bluetooth).
- PC → telefon over Bluetooth: store filer og mapper sendes også i små bidder, så de ikke løber ind i en tidsgrænse.

## 1.3.7 – 2026-10-22
### Nyt
- Bluetooth: "Søg via Bluetooth" på PC'en finder telefonen, selvom de aldrig har været på samme Wi-Fi. Telefonen dukker op på listen, og du forbinder med den 6-cifrede kode – direkte over Bluetooth.
### Forbedret
- PC'en prøver nu alle parrede telefoner, også når navnet i Bluetooth (fx "Galaxy S24") er et andet end navnet i h4xtor share. Høretelefoner og tastaturer bliver ladt i fred.
- En telefon, der kun er forbundet via Bluetooth, bliver på listen (offline), når den er uden for rækkevidde, og forbinder selv igen, når den er tilbage – også efter genstart af PC'en.
- Fejlbeskeder siger nu præcis, hvad der mangler, fx "Slå 'Tillad forbindelse via Bluetooth' til i appen" eller "Bluetooth er slået fra på PC'en".
### Rettet
- Bluetooth: telefon og PC fandt ikke hinanden, selvom de var parret i Windows' Bluetooth-menu. Før virkede Bluetooth kun, hvis de først havde været forbundet over Wi-Fi.
- "Forbind via Bluetooth" i enhedens menu mangler ikke længere for telefoner, der blev parret før version 1.3.6.

## 1.3.6 – 2026-10-21
### Nyt
- Bluetooth: PC og telefon kan nu forbinde via Bluetooth, når der hverken er Wi-Fi eller Wi-Fi Direct. Slå "Tillad forbindelse via Bluetooth" til på telefonen (fanen Del), og par telefonen med PC'en i Bluetooth-indstillingerne én gang. PC'en skifter selv til Bluetooth, når Wi-Fi ikke kan nå telefonen, og tilbage igen, når Wi-Fi virker. Alt virker – bare langsommere. Kræver Windows eller Linux på PC'en.
### Rettet
- Wi-Fi Direct: fejlteksten i "Vælg navn og kode" forsvinder, så snart du retter.

## 1.3.5 – 2026-10-21
### Nyt
- Wi-Fi Direct: vælg selv netværksnavn og kode under "Vælg navn og kode" på telefonen. Navnet bliver "DIRECT-h4-" + det, du skriver (fx "DIRECT-h4-Lennart" – Android kræver den start), og koden skal være 8–63 tegn. "Brug automatisk" giver den korte automatiske kode tilbage.

## 1.3.4 – 2026-10-21
### Nyt
- Højreklik på et billede i Chrome: "Send billede til S24 Ultra" (eller en anden enhed eller alle enheder) sender selve billedet direkte til telefonen – ligesom Join.
### Forbedret
- Wi-Fi Direct har nu et kort netværksnavn (fx "DIRECT-h4-427") og en kort adgangskode på 8 tegn med små bogstaver og tal, uden tegn der ligner hinanden. Det er meget nemmere at taste ind på PC'en. Telefonen laver den nye kode første gang, du starter Wi-Fi Direct efter opdateringen.
- Billeder fra Google Fotos sendes i fuld størrelse og får et pænt navn som "Billede-20261021-120000.jpg".
- Chrome-udvidelsen opdaterer sig selv, når PC-appen bliver opdateret (næste gang Chrome starter).
### Rettet
- Opdateringsloggen viser hele teksten i stedet for at stoppe midt i en sætning.

## 1.3.3 – 2026-10-14
### Nyt
- Bank-tilstand er nu en knap med til/fra: "Bank-tilstand til" slukker alt det følsomme, og "Bank-tilstand fra" tænder præcis de funktioner igen, som var slået til før. (Hjælpefunktionen "send når du kopierer" skal du selv tænde igen i Android – appen viser vej.)

## 1.3.2 – 2026-10-14
### Nyt
- "Bank-tilstand" i Indstillinger: ét tryk slukker alt det følsomme (tilgængelighed/"send når du kopierer", notifikationer på PC'en, SMS og skærmoptagelse), så bankapps, der ellers spærrer, åbner igen. Fildeling virker stadig, og du kan tænde funktionerne igen bagefter.

## 1.3.1 – 2026-10-13
### Rettet
- Skærmbillede fra PC'en: venter nu op til 15 sekunder på det første billede, i stedet for 6. Kunne før fejle på langsommere telefoner lige efter du godkendte optagelsen.

## 1.3.0 – 2026-10-13
### Nyt
- Automatisk opdatering af PC-appen (Windows) og Android-appen direkte fra GitHub – den spørger altid først.
- Se hvad der er nyt, før du opdaterer, også for versioner du har sprunget over.
- “Opdateringslog” i Indstillinger – virker også uden internet.
- Knappen “Søg efter opdatering nu” og valget “Søg automatisk efter opdateringer”.
- “Velkommen til version …” første gang, du åbner en ny version.
### Forbedret
- Hver fil kontrolleres med en SHA-256-tjeksum, før den installeres.
- Fejler en opdatering på PC'en, sættes din tidligere version automatisk tilbage.

## 1.2.0 – 2026-10-10
### Nyt
- Telefonens notifikationer på PC'en – svar og afvis direkte derfra. Vælg selv hvilke apps.
- SMS på PC'en: læs, skriv og få nye beskeder med det samme.
- Tag et skærmbillede af telefonen fra PC'en.
- Find min telefon: ringer højt, også på lydløs, og vibrerer.
- Fjernbetjening: lydstyrke, oplæsning og baggrundsbillede.
- Send til alle enheder på én gang – fra PC, telefon og Chrome.
- Google Drive (valgfri) under Indstillinger → Sky.

## 1.1.9 – 2026-10-09
### Nyt
- Del med iPhone via Safari – ingen app nødvendig.
### Forbedret
- Overførsler: filtre, overblik og sletning direkte i appen.
