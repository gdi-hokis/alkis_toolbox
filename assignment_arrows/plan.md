# Plan: Performance-Analyse calculate_assignment_arrows.py

## Status: Bewertung/Planung (kein Code schreiben)

## Identifizierte Bottlenecks (nach Impact sortiert)

### 1. Dreifach-Redundanz in SCALE_CONFIG [HÖCHSTER IMPACT]
- Scales 250, 500, 1000 verwenden IDENTISCH dieselbe `labels_1000`, `label1000_to_parcel`, `parcels_with_labels_1000`
- Alle teuren Operationen (check_label_inside, find_nearest, build_arrow inkl. buffer/boundary) laufen 3× für dieselben Label-Parcel-Paare
- Nur `font_size`, `min_arrow`, `max_arrow` unterscheiden sich
- Fix: Matching EINMALIG laufen, dann pro gematchtem Paar für alle 3 Scales Pfeil berechnen

### 2. SpatialJoin_analysis → scratchGDB [HOHER IMPACT]
- 2× pro Gemeinde: schreibt temporäre FC auf Disk, liest zurück, löscht
- Alternative: Nach Labels iterieren, spatial_index.query() + parcel_geometry.contains(label_point) in-memory
- Parcels und spatial_index sind bereits geladen

### 3. SHAPE@ für Parcels (Lazy Loading) [MITTLERER IMPACT]
- Für 10k+ Flurstücke pro Gemeinde: volle Geometry für ALLE geladen
- geometry.buffer(), .boundary(), .within() nur für ~5% der Labels nötig
- WKB speichern: cursor mit SHAPE@WKB, bei Bedarf arcpy.FromWKB() aufrufen
- area, perimeter, labelPoint bereits als Skalare extrahiert – geometry nur für set_start_and_end + within-Check

### 4. SHAPE@ für Labels → gar nicht nötig [MITTLERER IMPACT]
- label["geometry"] wird nur für .firstPoint verwendet
- x, y sind BEREITS als Skalare gespeichert
- SHAPE@ für Labels komplett weglassen, PointGeometry nur für ~5% rekonstruieren

### 5. form_index Vorberechnung [KLEINER IMPACT]
- area und perimeter bereits gespeichert
- form_index in load_parcels vorberechnen, statt es in set_start_and_end 3× zu berechnen

## Bewertung der User-Ideen

### Idee: pandas + WKB für Labels
- WKB-Ansatz für Labels: **korrekte Richtung**, aber zu weit gedacht
- label["geometry"] wird nur für firstPoint verwendet → x, y BEREITS in dict
- Besser: SHAPE@ ganz weglassen, PointGeometry on-demand rekonstruieren
- pandas: kein Mehrwert, da Algorithmus sequenziell, nicht vektorisierbar (used_parcels State!)
- Verdict: WKB-Idee gute Richtung, aber simpler ohne pandas umzusetzen

### Idee: pandas + WKB für Parcels
- WKB-Ansatz: **sinnvoll** für memory + cursor-Ladezeit
- Geometry-Objekte für 95% der Flurstücke nie benötigt → lazy sehr effizient
- pandas: kein Mehrwert für diesen sequenziellen Algorithmus
- Verdict: WKB ja (in bestehende dicts integrieren), pandas nein
