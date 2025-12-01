import ephem
import math
import requests
import datetime

# 表示用に日本時間(JST)のタイムゾーン定義
JST = datetime.timezone(datetime.timedelta(hours=9))

def get_terrain_altitude(lat, lon):
    """
    Open-Elevation APIを使用して指定座標の標高(m)を取得する
    修正: GETメソッドからPOSTメソッドに変更し、JSONペイロードの形式を修正
    """
    url = 'https://api.open-elevation.com/api/v1/lookup'
    # APIの仕様に合わせて辞書のリスト形式にする
    payload = {'locations': [{'latitude': lat, 'longitude': lon}]}
    try:
        r = requests.post(url, json=payload, timeout=10)
        data = r.json()
        return data['results'][0]['elevation']
    except Exception as e:
        print(f"API Error (get_terrain_altitude): {e}")
        return 0  # エラー時は平地と仮定

def calculate_destination(lat, lon, distance_km, bearing_deg):
    """
    指定地点から、指定距離・指定方位にある地点の座標を計算する
    """
    R = 6371.0 # 地球の半径 (km)
    
    lat_rad = math.radians(lat)
    lon_rad = math.radians(lon)
    bearing_rad = math.radians(bearing_deg)
    
    new_lat_rad = math.asin(math.sin(lat_rad) * math.cos(distance_km / R) +
                            math.cos(lat_rad) * math.sin(distance_km / R) * math.cos(bearing_rad))
    
    new_lon_rad = lon_rad + math.atan2(math.sin(bearing_rad) * math.sin(distance_km / R) * math.cos(lat_rad),
                                       math.cos(distance_km / R) - math.sin(lat_rad) * math.sin(new_lat_rad))
    
    return math.degrees(new_lat_rad), math.degrees(new_lon_rad)

def get_horizon_elevation_angle(obs_lat, obs_lon, obs_alt, azimuth, check_distance_km=20, step_km=1.0):
    """
    特定の方位(azimuth)に対して、地形による最大仰角を計算する。
    """
    max_angle = 0.0
    
    points = []
    distances = []
    
    d = step_km
    while d <= check_distance_km:
        lat, lon = calculate_destination(obs_lat, obs_lon, d, azimuth)
        points.append({"latitude": lat, "longitude": lon})
        distances.append(d)
        d += step_km

    if not points:
        return 0.0

    url = 'https://api.open-elevation.com/api/v1/lookup'
    payload = {'locations': points}
    
    try:
        r = requests.post(url, json=payload, timeout=10)
        results = r.json()['results']
        
        for i, item in enumerate(results):
            terrain_alt = item['elevation']
            dist_m = distances[i] * 1000.0
            
            relative_height = terrain_alt - obs_alt
            
            # 観測点より低い場所は無視
            if relative_height <= 0:
                continue
                
            angle = math.degrees(math.atan(relative_height / dist_m))
            
            if angle > max_angle:
                max_angle = angle
                
    except Exception as e:
        print(f"Elevation API Error (get_horizon): {e}")
        
    return max_angle

def calculate_actual_sunset(target_date_str, lat, lon):
    """
    指定日・指定座標における、地形を考慮した日の入り時刻を計算
    """
    observer = ephem.Observer()
    observer.lat = str(lat)
    observer.lon = str(lon)
    # PyEphemの日付はUTCとして扱われるため、入力文字列をUTCとみなしてセット
    observer.date = target_date_str
    
    # 観測地点の標高を取得（修正済みの関数を使用）
    print("観測地点の標高を取得中...")
    my_elevation = get_terrain_altitude(lat, lon)
    observer.elevation = my_elevation
    print(f"観測地点: 標高 {my_elevation}m")

    # 標準的な日の入り時刻（地平線）
    sun = ephem.Sun()
    standard_sunset = observer.next_setting(sun)
    
    # 表示用にJSTへ変換
    std_sunset_dt = standard_sunset.datetime().replace(tzinfo=datetime.timezone.utc)
    print(f"標準的な日の入り(地平線): {std_sunset_dt.astimezone(JST).strftime('%Y-%m-%d %H:%M:%S')} (JST)")

    # 計算開始時刻（標準日の入りの90分前からチェック開始）
    current_check_time = standard_sunset.datetime() - datetime.timedelta(minutes=90)
    end_check_time = standard_sunset.datetime() + datetime.timedelta(minutes=10)
    
    step_minutes = 2
    actual_sunset_time = None
    
    print("\n--- 地形との交差判定を開始 ---")
    
    while current_check_time < end_check_time:
        observer.date = current_check_time
        sun.compute(observer)
        
        sun_az = math.degrees(sun.az)
        sun_alt = math.degrees(sun.alt)
        
        # 太陽が地平線より下の場合
        if sun_alt < 0:
            actual_sunset_time = current_check_time
            print("既に地平線の下に沈んでいます。")
            break

        # その方位にある地形の最大仰角を取得 (20km先までチェック)
        terrain_angle = get_horizon_elevation_angle(lat, lon, my_elevation, sun_az, check_distance_km=20, step_km=2.0)
        
        # JST変換して表示
        jst_time = current_check_time.replace(tzinfo=datetime.timezone.utc).astimezone(JST)
        print(f"時刻(JST): {jst_time.strftime('%H:%M')} | 太陽方位: {sun_az:.1f}° | 太陽高度: {sun_alt:.2f}° | 地形仰角: {terrain_angle:.2f}°")
        
        # 太陽高度が地形仰角を下回ったら隠れたと判定
        if sun_alt <= terrain_angle:
            actual_sunset_time = current_check_time
            print(f"★ 山に隠れました！")
            break
            
        current_check_time += datetime.timedelta(minutes=step_minutes)

    return actual_sunset_time

if __name__ == "__main__":
    # 例: 長野県松本市
    lat = 36.238
    lon = 137.964
    # 計算基準日 (UTCで指定するか、JSTから9時間引いた時間を指定するのが無難)
    # ここでは単純に文字列を渡していますが、本来はdatetimeオブジェクト変換推奨
    date_str = '2023/10/25 03:00:00' # UTCの午前3時 = 日本時間の正午12時

    print(f"計算対象(UTC): {date_str}, 座標: {lat}, {lon}")
    
    real_sunset_utc = calculate_actual_sunset(date_str, lat, lon)

    if real_sunset_utc:
        # UTC -> JST変換
        if isinstance(real_sunset_utc, datetime.datetime):
             real_sunset_jst = real_sunset_utc.replace(tzinfo=datetime.timezone.utc).astimezone(JST)
        else:
             # ephem.Date型の場合のケア
             real_sunset_jst = real_sunset_utc.datetime().replace(tzinfo=datetime.timezone.utc).astimezone(JST)
             
        print(f"\n予想される地形考慮後の日の入り時刻: {real_sunset_jst.strftime('%Y/%m/%d %H:%M:%S')} (JST)")
    else:
        print("計算範囲内で日の入りを確認できませんでした。")