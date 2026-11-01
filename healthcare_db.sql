-- ============================================================
-- MediAssist  -  Healthcare Project  -  Database Schema + Sample Data
-- ------------------------------------------------------------
-- HOW TO RUN (MySQL 8+ / MariaDB 10.5+):
--     mysql -u root -p < healthcare_db.sql
-- This DROPS and re-creates `mediassist_care_db`, so any old data in
-- THAT database is lost. It is a brand new, separate database name
-- (NOT the old `healthcare_db`), so your original `healthcare_db`
-- is left completely untouched.
--
-- TABLE OVERVIEW
--   USER              every account (patients + doctors), hashed password
--   PATIENT_PROFILE   1-to-1 with USER (role = patient): height, weight, blood group,
--                      qr_token (unique code behind that patient's QR code)
--   DOCTOR_PROFILE    1-to-1 with USER (role = doctor):  specialization, registration_no
--   MEALS             food log rows         (belongs to a patient)
--   FITNESS           workout log rows      (belongs to a patient)
--   APPOINTMENT       patient <-> doctor booking. Doctor approves it:
--                       pending -> confirmed -> completed   (or cancelled)
--   PRESCRIPTION      one visit's prescription (patient + doctor + date)
--   MEDICINE          medicines inside a prescription
--
-- RELATIONSHIPS
--   USER 1--1 PATIENT_PROFILE 1--* MEALS / FITNESS / APPOINTMENT / PRESCRIPTION
--   USER 1--1 DOCTOR_PROFILE  1--* APPOINTMENT / PRESCRIPTION
--   PRESCRIPTION 1--* MEDICINE
--
-- QR CODE FEATURE
--   Every patient has a unique, random `qr_token` on PATIENT_PROFILE.
--   The dashboard turns that token into a QR code that encodes a link
--   to /report/<qr_token>. A doctor who scans it (and is logged in)
--   sees that patient's full medical report. The patient can regenerate
--   the token at any time from the dashboard, which instantly invalidates
--   the old QR code/link.
-- ============================================================

DROP DATABASE IF EXISTS mediassist_care_db;
CREATE DATABASE mediassist_care_db;
USE mediassist_care_db;

-- ------------------------------------------------------------
-- USER  (login / auth for everyone)
-- Patients log in with EMAIL + password.
-- Doctors  log in with REGISTRATION NO (see DOCTOR_PROFILE) + password.
-- Passwords are stored HASHED (werkzeug pbkdf2), never plain text.
-- Self sign-up on the website always creates role = 'patient'.
-- Doctor accounts are created by the hospital/admin (see sample data).
-- ------------------------------------------------------------
CREATE TABLE USER (
    user_id       INT AUTO_INCREMENT PRIMARY KEY,
    name          VARCHAR(100) NOT NULL,
    email         VARCHAR(150) NOT NULL UNIQUE,
    password      VARCHAR(255) NOT NULL,
    role          ENUM('patient', 'doctor', 'admin') NOT NULL DEFAULT 'patient',
    date_of_birth DATE,
    gender        ENUM('Male', 'Female', 'Other'),
    phone         VARCHAR(15),
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE PATIENT_PROFILE (
    patient_id  INT AUTO_INCREMENT PRIMARY KEY,
    user_id     INT NOT NULL UNIQUE,
    height      DECIMAL(5,2),   -- cm
    weight      DECIMAL(5,2),   -- kg
    blood_group VARCHAR(5),
    qr_token    VARCHAR(64) UNIQUE,   -- unique code behind this patient's personal QR code
    FOREIGN KEY (user_id) REFERENCES USER(user_id) ON DELETE CASCADE
);

CREATE TABLE DOCTOR_PROFILE (
    doctor_id       INT AUTO_INCREMENT PRIMARY KEY,
    user_id         INT NOT NULL UNIQUE,
    registration_no VARCHAR(30) NOT NULL UNIQUE,   -- doctor's login ID, different for every doctor
    specialization  VARCHAR(100),
    qualification   VARCHAR(150),
    license_no      VARCHAR(50) UNIQUE,
    FOREIGN KEY (user_id) REFERENCES USER(user_id) ON DELETE CASCADE
);

CREATE TABLE MEALS (
    meal_id    INT AUTO_INCREMENT PRIMARY KEY,
    patient_id INT NOT NULL,
    food       VARCHAR(150) NOT NULL,
    calories   INT,
    date       DATE NOT NULL,
    FOREIGN KEY (patient_id) REFERENCES PATIENT_PROFILE(patient_id) ON DELETE CASCADE
);

CREATE TABLE FITNESS (
    fitness_id INT AUTO_INCREMENT PRIMARY KEY,
    patient_id INT NOT NULL,
    exercise   VARCHAR(150) NOT NULL,
    duration   INT,        -- minutes
    calories   INT,        -- calories burned
    date       DATE NOT NULL,
    FOREIGN KEY (patient_id) REFERENCES PATIENT_PROFILE(patient_id) ON DELETE CASCADE
);

-- status flow: patient books -> 'pending' -> doctor approves -> 'confirmed'
--              -> after the visit doctor marks 'completed'.
--              Doctor may decline, or patient may cancel -> 'cancelled'.
CREATE TABLE APPOINTMENT (
    appointment_id INT AUTO_INCREMENT PRIMARY KEY,
    patient_id     INT NOT NULL,
    doctor_id      INT NOT NULL,
    date_time      DATETIME NOT NULL,
    status         ENUM('pending', 'confirmed', 'completed', 'cancelled') DEFAULT 'pending',
    FOREIGN KEY (patient_id) REFERENCES PATIENT_PROFILE(patient_id) ON DELETE CASCADE,
    FOREIGN KEY (doctor_id) REFERENCES DOCTOR_PROFILE(doctor_id) ON DELETE CASCADE
);

CREATE TABLE PRESCRIPTION (
    prescription_id INT AUTO_INCREMENT PRIMARY KEY,
    patient_id      INT NOT NULL,
    doctor_id       INT NOT NULL,
    date            DATE NOT NULL,
    file_url        VARCHAR(255),
    FOREIGN KEY (patient_id) REFERENCES PATIENT_PROFILE(patient_id) ON DELETE CASCADE,
    FOREIGN KEY (doctor_id) REFERENCES DOCTOR_PROFILE(doctor_id) ON DELETE CASCADE
);

CREATE TABLE MEDICINE (
    medicine_id     INT AUTO_INCREMENT PRIMARY KEY,
    prescription_id INT NOT NULL,
    name            VARCHAR(150) NOT NULL,
    dosage          VARCHAR(50),
    frequency       VARCHAR(50),
    duration        VARCHAR(50),
    FOREIGN KEY (prescription_id) REFERENCES PRESCRIPTION(prescription_id) ON DELETE CASCADE
);

CREATE INDEX idx_meals_patient_date     ON MEALS(patient_id, date);
CREATE INDEX idx_fitness_patient_date   ON FITNESS(patient_id, date);
CREATE INDEX idx_appointment_doctor     ON APPOINTMENT(doctor_id, date_time);
CREATE INDEX idx_appointment_patient    ON APPOINTMENT(patient_id, date_time);

-- ============================================================
-- SAMPLE DATA   (dates are relative to the day you run this file,
--                so the dashboard graph always looks current)
-- ------------------------------------------------------------
-- DOCTOR LOGINS  (Doctor Login tab: Registration No + Password)
--   MED-1001  Sneha@1001   Dr. Sneha Verma   General Physician
--   MED-1002  Rohit@1002   Dr. Rohit Sharma  Cardiologist
--   MED-1003  Anjali@1003  Dr. Anjali Mehta  Dermatologist
--   MED-1004  Vikram@1004  Dr. Vikram Singh  Orthopedic Surgeon
-- PATIENT LOGINS (Login tab: Email + Password)
--   aarav@demo.com  Patient@123
--   priya@demo.com  Patient@456
-- ============================================================

INSERT INTO USER (user_id, name, email, password, role, date_of_birth, gender, phone) VALUES
(1, 'Sneha Verma', 'sneha.verma@mediassist.com', 'pbkdf2:sha256:1000000$EUngDksvDfJz1ttD$d7b708c16985912900acd04504fb12f968908242f7502770fd365b8539aacc15', 'doctor', '1985-03-14', 'Female', '9876511001'),
(2, 'Rohit Sharma', 'rohit.sharma@mediassist.com', 'pbkdf2:sha256:1000000$WtGSGZjXGlfYVKSk$df29fe79ee9f03c7d1800caade33c3db81109c7ead80882bfeed8d97449d4205', 'doctor', '1980-07-22', 'Male', '9876511002'),
(3, 'Anjali Mehta', 'anjali.mehta@mediassist.com', 'pbkdf2:sha256:1000000$6RryuBq1pBLlmu9H$07d1a9e9d6b46195844934cf218ba1075dd49d09b4f3c573f71214155bceb910', 'doctor', '1988-01-30', 'Female', '9876511003'),
(4, 'Vikram Singh', 'vikram.singh@mediassist.com', 'pbkdf2:sha256:1000000$fQYyp28ZsGEkK8wn$913f0de3730fae9e5dc25e00b07828fadf202a69ed2e029cc7db055fb8e0306b', 'doctor', '1982-09-09', 'Male', '9876511004'),
(5, 'Aarav Patel', 'aarav@demo.com', 'pbkdf2:sha256:1000000$wt0HMSSXTT9XMp99$c9040117dd4cffd337832ddbc05b9ddc4019cfccc075c7b6f63be7edbefaaaf5', 'patient', '1998-04-12', 'Male', '9876500001'),
(6, 'Priya Nair', 'priya@demo.com', 'pbkdf2:sha256:1000000$n1wsh0Zvxkintmzi$5b33f9f8173dc50f8522bf70cf0cb1306e9a705e872a1869d1ee879855ae16ed', 'patient', '2000-11-03', 'Female', '9876500002');

INSERT INTO DOCTOR_PROFILE (doctor_id, user_id, registration_no, specialization, qualification, license_no) VALUES
(1, 1, 'MED-1001', 'General Physician', 'MBBS, MD (General Medicine)', 'LIC-MP-48211'),
(2, 2, 'MED-1002', 'Cardiologist', 'MBBS, DM (Cardiology)', 'LIC-MP-51876'),
(3, 3, 'MED-1003', 'Dermatologist', 'MBBS, MD (Dermatology)', 'LIC-MP-39027'),
(4, 4, 'MED-1004', 'Orthopedic Surgeon', 'MBBS, MS (Orthopaedics)', 'LIC-MP-60344');

INSERT INTO PATIENT_PROFILE (patient_id, user_id, height, weight, blood_group, qr_token) VALUES
(1, 5, 172.5, 68.0, 'B+', 'aarav-demo-qr-3f9c81a2e6'),
(2, 6, 161.0, 55.5, 'O+', 'priya-demo-qr-7b21d94f0c');

INSERT INTO MEALS (patient_id, food, calories, date) VALUES
(1, 'Paneer sandwich', 393, DATE_SUB(CURDATE(), INTERVAL 0 DAY)),
(1, 'Chapati with paneer curry', 564, DATE_SUB(CURDATE(), INTERVAL 0 DAY)),
(1, 'Veg khichdi', 464, DATE_SUB(CURDATE(), INTERVAL 0 DAY)),
(1, 'Fruit salad', 180, DATE_SUB(CURDATE(), INTERVAL 0 DAY)),
(1, 'Oats with banana', 303, DATE_SUB(CURDATE(), INTERVAL 1 DAY)),
(1, 'Fruit salad', 192, DATE_SUB(CURDATE(), INTERVAL 1 DAY)),
(1, 'Grilled chicken salad', 423, DATE_SUB(CURDATE(), INTERVAL 1 DAY)),
(1, 'Oats with banana', 326, DATE_SUB(CURDATE(), INTERVAL 2 DAY)),
(1, 'Dal, rice and sabzi', 604, DATE_SUB(CURDATE(), INTERVAL 2 DAY)),
(1, 'Veg khichdi', 445, DATE_SUB(CURDATE(), INTERVAL 2 DAY)),
(1, 'Oats with banana', 303, DATE_SUB(CURDATE(), INTERVAL 3 DAY)),
(1, 'Grilled chicken salad', 446, DATE_SUB(CURDATE(), INTERVAL 3 DAY)),
(1, 'Veg khichdi', 437, DATE_SUB(CURDATE(), INTERVAL 3 DAY)),
(1, 'Fruit salad', 180, DATE_SUB(CURDATE(), INTERVAL 3 DAY)),
(1, 'Poha', 297, DATE_SUB(CURDATE(), INTERVAL 4 DAY)),
(1, 'Masala dosa', 463, DATE_SUB(CURDATE(), INTERVAL 4 DAY)),
(1, 'Masala dosa', 496, DATE_SUB(CURDATE(), INTERVAL 4 DAY)),
(1, 'Idli sambar', 282, DATE_SUB(CURDATE(), INTERVAL 5 DAY)),
(1, 'Dal, rice and sabzi', 635, DATE_SUB(CURDATE(), INTERVAL 5 DAY)),
(1, 'Chapati with paneer curry', 568, DATE_SUB(CURDATE(), INTERVAL 5 DAY)),
(1, 'Paneer sandwich', 424, DATE_SUB(CURDATE(), INTERVAL 6 DAY)),
(1, 'Veg khichdi', 437, DATE_SUB(CURDATE(), INTERVAL 6 DAY)),
(1, 'Chapati with paneer curry', 596, DATE_SUB(CURDATE(), INTERVAL 6 DAY)),
(1, 'Fruit salad', 180, DATE_SUB(CURDATE(), INTERVAL 6 DAY)),
(1, 'Paneer sandwich', 401, DATE_SUB(CURDATE(), INTERVAL 7 DAY)),
(1, 'Grilled chicken salad', 416, DATE_SUB(CURDATE(), INTERVAL 7 DAY)),
(1, 'Vegetable soup', 167, DATE_SUB(CURDATE(), INTERVAL 7 DAY)),
(1, 'Poha', 295, DATE_SUB(CURDATE(), INTERVAL 8 DAY)),
(1, 'Fruit salad', 164, DATE_SUB(CURDATE(), INTERVAL 8 DAY)),
(1, 'Dal, rice and sabzi', 636, DATE_SUB(CURDATE(), INTERVAL 8 DAY)),
(1, 'Oats with banana', 331, DATE_SUB(CURDATE(), INTERVAL 9 DAY)),
(1, 'Grilled chicken salad', 444, DATE_SUB(CURDATE(), INTERVAL 9 DAY)),
(1, 'Chapati with paneer curry', 587, DATE_SUB(CURDATE(), INTERVAL 9 DAY)),
(1, 'Fruit salad', 180, DATE_SUB(CURDATE(), INTERVAL 9 DAY)),
(1, 'Paneer sandwich', 419, DATE_SUB(CURDATE(), INTERVAL 10 DAY)),
(1, 'Veg khichdi', 453, DATE_SUB(CURDATE(), INTERVAL 10 DAY)),
(1, 'Grilled chicken salad', 429, DATE_SUB(CURDATE(), INTERVAL 10 DAY)),
(1, 'Poha', 275, DATE_SUB(CURDATE(), INTERVAL 11 DAY)),
(1, 'Chapati with paneer curry', 565, DATE_SUB(CURDATE(), INTERVAL 11 DAY)),
(1, 'Masala dosa', 496, DATE_SUB(CURDATE(), INTERVAL 11 DAY)),
(1, 'Paneer sandwich', 411, DATE_SUB(CURDATE(), INTERVAL 12 DAY)),
(1, 'Grilled chicken salad', 438, DATE_SUB(CURDATE(), INTERVAL 12 DAY)),
(1, 'Veg khichdi', 448, DATE_SUB(CURDATE(), INTERVAL 12 DAY)),
(1, 'Fruit salad', 180, DATE_SUB(CURDATE(), INTERVAL 12 DAY)),
(1, 'Oats with banana', 326, DATE_SUB(CURDATE(), INTERVAL 13 DAY)),
(1, 'Dal, rice and sabzi', 610, DATE_SUB(CURDATE(), INTERVAL 13 DAY)),
(1, 'Grilled chicken salad', 431, DATE_SUB(CURDATE(), INTERVAL 13 DAY)),
(2, 'Oats with banana', 320, DATE_SUB(CURDATE(), INTERVAL 0 DAY)),
(2, 'Veg khichdi', 450, DATE_SUB(CURDATE(), INTERVAL 0 DAY)),
(2, 'Masala dosa', 480, DATE_SUB(CURDATE(), INTERVAL 0 DAY)),
(2, 'Oats with banana', 320, DATE_SUB(CURDATE(), INTERVAL 1 DAY)),
(2, 'Dal, rice and sabzi', 620, DATE_SUB(CURDATE(), INTERVAL 1 DAY)),
(2, 'Curd and fruits', 220, DATE_SUB(CURDATE(), INTERVAL 1 DAY)),
(2, 'Paneer sandwich', 410, DATE_SUB(CURDATE(), INTERVAL 2 DAY)),
(2, 'Fruit salad', 180, DATE_SUB(CURDATE(), INTERVAL 2 DAY)),
(2, 'Masala dosa', 480, DATE_SUB(CURDATE(), INTERVAL 2 DAY)),
(2, 'Paneer sandwich', 410, DATE_SUB(CURDATE(), INTERVAL 3 DAY)),
(2, 'Fruit salad', 180, DATE_SUB(CURDATE(), INTERVAL 3 DAY)),
(2, 'Curd and fruits', 220, DATE_SUB(CURDATE(), INTERVAL 3 DAY)),
(2, 'Poha', 280, DATE_SUB(CURDATE(), INTERVAL 4 DAY)),
(2, 'Veg khichdi', 450, DATE_SUB(CURDATE(), INTERVAL 4 DAY)),
(2, 'Grilled chicken salad', 430, DATE_SUB(CURDATE(), INTERVAL 4 DAY)),
(2, 'Oats with banana', 320, DATE_SUB(CURDATE(), INTERVAL 5 DAY)),
(2, 'Fruit salad', 180, DATE_SUB(CURDATE(), INTERVAL 5 DAY)),
(2, 'Masala dosa', 480, DATE_SUB(CURDATE(), INTERVAL 5 DAY)),
(2, 'Paneer sandwich', 410, DATE_SUB(CURDATE(), INTERVAL 6 DAY)),
(2, 'Dal, rice and sabzi', 620, DATE_SUB(CURDATE(), INTERVAL 6 DAY)),
(2, 'Grilled chicken salad', 430, DATE_SUB(CURDATE(), INTERVAL 6 DAY));

INSERT INTO FITNESS (patient_id, exercise, duration, calories, date) VALUES
(1, 'Jogging', 30, 265, DATE_SUB(CURDATE(), INTERVAL 0 DAY)),
(1, 'Cycling', 45, 274, DATE_SUB(CURDATE(), INTERVAL 1 DAY)),
(1, 'Jogging', 35, 273, DATE_SUB(CURDATE(), INTERVAL 3 DAY)),
(1, 'Cycling', 40, 265, DATE_SUB(CURDATE(), INTERVAL 4 DAY)),
(1, 'Jogging', 35, 256, DATE_SUB(CURDATE(), INTERVAL 6 DAY)),
(1, 'Cycling', 35, 284, DATE_SUB(CURDATE(), INTERVAL 7 DAY)),
(1, 'Swimming', 25, 270, DATE_SUB(CURDATE(), INTERVAL 8 DAY)),
(1, 'Cycling', 30, 271, DATE_SUB(CURDATE(), INTERVAL 10 DAY)),
(1, 'Swimming', 35, 259, DATE_SUB(CURDATE(), INTERVAL 11 DAY)),
(1, 'Cycling', 35, 277, DATE_SUB(CURDATE(), INTERVAL 13 DAY)),
(2, 'Morning walk', 30, 120, DATE_SUB(CURDATE(), INTERVAL 0 DAY)),
(2, 'Jogging', 25, 260, DATE_SUB(CURDATE(), INTERVAL 1 DAY)),
(2, 'Cycling', 35, 280, DATE_SUB(CURDATE(), INTERVAL 3 DAY)),
(2, 'Strength training', 45, 300, DATE_SUB(CURDATE(), INTERVAL 4 DAY)),
(2, 'Morning walk', 30, 120, DATE_SUB(CURDATE(), INTERVAL 6 DAY));

INSERT INTO APPOINTMENT (appointment_id, patient_id, doctor_id, date_time, status) VALUES
(1, 1, 1, TIMESTAMP(CURDATE(), '17:30:00'),                       'confirmed'),
(2, 1, 2, TIMESTAMP(DATE_ADD(CURDATE(), INTERVAL 2 DAY), '11:00:00'), 'pending'),
(3, 1, 1, TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 20 DAY), '10:30:00'), 'completed'),
(4, 1, 3, TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 8 DAY), '15:00:00'),  'cancelled'),
(5, 2, 1, TIMESTAMP(DATE_ADD(CURDATE(), INTERVAL 1 DAY), '10:00:00'), 'pending'),
(6, 2, 3, TIMESTAMP(DATE_ADD(CURDATE(), INTERVAL 3 DAY), '12:30:00'), 'pending'),
(7, 2, 1, TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 12 DAY), '09:30:00'), 'completed');

INSERT INTO PRESCRIPTION (prescription_id, patient_id, doctor_id, date, file_url) VALUES
(1, 1, 1, DATE_SUB(CURDATE(), INTERVAL 20 DAY), NULL),
(2, 1, 2, DATE_SUB(CURDATE(), INTERVAL 45 DAY), NULL),
(3, 1, 1, DATE_SUB(CURDATE(), INTERVAL 90 DAY), NULL),
(4, 2, 1, DATE_SUB(CURDATE(), INTERVAL 12 DAY), NULL);

INSERT INTO MEDICINE (prescription_id, name, dosage, frequency, duration) VALUES
(1, 'Paracetamol', '500 mg', 'Twice a day', '5 days'),
(1, 'Vitamin D3', '60000 IU', 'Once a week', '8 weeks'),
(2, 'Atorvastatin', '10 mg', 'Once at night', '30 days'),
(3, 'Cetirizine', '10 mg', 'Once at night', '7 days'),
(4, 'Amoxicillin', '250 mg', 'Three times a day', '5 days');
