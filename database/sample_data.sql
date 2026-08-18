USE van_tracker_v2;

INSERT INTO vans (van_number, plate_number, capacity, speed_limit_kmh)
VALUES
    ('VAN-01', 'BA 2 KHA 1001', 15, 40.00),
    ('VAN-02', 'BA 2 KHA 1002', 15, 40.00);

INSERT INTO routes (name, school_name, school_lat, school_lng)
VALUES (
    'Kalanki–Baneshwor School Route',
    'Demonstration School',
    27.71200000,
    85.31800000
);

