import pandas as pd

def generate_kml(input_file, output_file):
    # Read the Excel file
    df = pd.read_excel(input_file)
    
    # Extract coordinates
    # We take all Start coordinates and the final End coordinate to create a continuous line
    coords = []
    for index, row in df.iterrows():
        # KML format is longitude,latitude,altitude
        coords.append(f"{row['StartLongitude']},{row['StartLatitude']},{row['StartAltitude']}")
    
    # Add the last end point
    last_row = df.iloc[-1]
    coords.append(f"{last_row['EndLongitude']},{last_row['EndLatitude']},{last_row['EndAltitude']}")
    
    coord_string = " ".join(coords)
    
    kml_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>Road Path from {input_file}</name>
    <Style id="roadStyle">
      <LineStyle>
        <color>ff0000ff</color>
        <width>4</width>
      </LineStyle>
    </Style>
    <Placemark>
      <name>Road Path</name>
      <styleUrl>#roadStyle</styleUrl>
      <LineString>
        <extrude>1</extrude>
        <tessellate>1</tessellate>
        <altitudeMode>relativeToGround</altitudeMode>
        <coordinates>
          {coord_string}
        </coordinates>
      </LineString>
    </Placemark>
  </Document>
</kml>"""

    with open(output_file, "w") as f:
        f.write(kml_content)
    print(f"KML file saved to {output_file}")

if __name__ == "__main__":
    generate_kml("gps_of_road.xlsx", "road_path.kml")
