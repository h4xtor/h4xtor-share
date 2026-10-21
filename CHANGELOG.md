# Opdateringslog

Appen læser denne fil, så formatet er fast:
`## <version> – <ÅÅÅÅ-MM-DD>`, derefter `### Nyt`, `### Forbedret` og `### Rettet` med punkter, der starter med `- `.
Nyeste version øverst. Udgivelsen fejler, hvis versionen mangler her.

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
