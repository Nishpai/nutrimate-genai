-- NutriMate schema. Safe to run more than once (CREATE TABLE IF NOT EXISTS).
-- Nutrition columns are NULL when the value is unknown. NULL never means zero.

CREATE TABLE IF NOT EXISTS users (
  id INT AUTO_INCREMENT PRIMARY KEY,
  email VARCHAR(190) NOT NULL UNIQUE,
  password_hash VARCHAR(100) NOT NULL,
  full_name VARCHAR(120) NOT NULL,
  role ENUM('user','admin') NOT NULL DEFAULT 'user',
  onboarded TINYINT(1) NOT NULL DEFAULT 0,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS profiles (
  user_id INT PRIMARY KEY,
  sex ENUM('male','female') NULL,
  age SMALLINT NULL,
  height_cm DECIMAL(5,1) NULL,
  weight_kg DECIMAL(5,1) NULL,
  activity VARCHAR(20) NULL,
  goal ENUM('lose','maintain','gain') NULL,
  diet ENUM('any','eggetarian','vegetarian','vegan') NOT NULL DEFAULT 'any',
  allergies JSON NOT NULL,
  restrictions JSON NOT NULL,
  cuisines JSON NOT NULL,
  calorie_target INT NULL,
  protein_target_g INT NULL,
  carbs_target_g INT NULL,
  fat_target_g INT NULL,
  fiber_target_g INT NULL,
  meals_per_day TINYINT NOT NULL DEFAULT 3,
  max_minutes INT NULL,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  CONSTRAINT fk_profiles_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS profile_history (
  id INT AUTO_INCREMENT PRIMARY KEY,
  user_id INT NOT NULL,
  snapshot JSON NOT NULL,
  changed_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_ph_user (user_id, changed_at),
  CONSTRAINT fk_ph_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS recipes (
  recipe_id INT PRIMARY KEY,
  name VARCHAR(255) NOT NULL,
  category VARCHAR(80) NULL,
  keywords TEXT NULL,
  ingredients TEXT NULL,
  instructions MEDIUMTEXT NULL,
  description TEXT NULL,
  total_minutes DOUBLE NULL,
  servings INT NULL,
  year SMALLINT NULL,
  calories_kcal DOUBLE NULL,
  protein_g DOUBLE NULL,
  carbs_g DOUBLE NULL,
  fat_g DOUBLE NULL,
  fiber_g DOUBLE NULL,
  sugar_g DOUBLE NULL,
  sodium_mg DOUBLE NULL,
  sat_fat_g DOUBLE NULL,
  nutrition_status VARCHAR(20) NOT NULL,
  cuisine VARCHAR(40) NOT NULL,
  meal_type VARCHAR(20) NOT NULL,
  is_eggetarian TINYINT(1) NOT NULL,
  is_vegetarian TINYINT(1) NOT NULL,
  is_vegan TINYINT(1) NOT NULL,
  allergens_found VARCHAR(255) NOT NULL DEFAULT '',
  in_cf_data TINYINT(1) NOT NULL,
  n_ratings INT NOT NULL DEFAULT 0,
  mean_rating DOUBLE NULL,
  source VARCHAR(120) NOT NULL,
  INDEX idx_recipes_name (name),
  INDEX idx_recipes_meal (meal_type),
  INDEX idx_recipes_cuisine (cuisine)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS foods (
  food_id VARCHAR(40) PRIMARY KEY,
  name VARCHAR(255) NOT NULL,
  source VARCHAR(120) NOT NULL,
  food_group VARCHAR(80) NULL,
  kcal_100g DOUBLE NULL,
  protein_100g DOUBLE NULL,
  carbs_100g DOUBLE NULL,
  fat_100g DOUBLE NULL,
  fiber_100g DOUBLE NULL,
  sugar_100g DOUBLE NULL,
  sodium_100g DOUBLE NULL,
  serving_unit VARCHAR(80) NULL,
  kcal_serving DOUBLE NULL,
  protein_serving DOUBLE NULL,
  carbs_serving DOUBLE NULL,
  fat_serving DOUBLE NULL,
  fiber_serving DOUBLE NULL,
  dataset_id INT NULL,
  INDEX idx_foods_name (name),
  INDEX idx_foods_source (source)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS interactions (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  user_id INT NOT NULL,
  item_type ENUM('recipe','food') NOT NULL DEFAULT 'recipe',
  item_id VARCHAR(40) NOT NULL,
  action ENUM('like','dislike','save','unsave','view','clear') NOT NULL,
  created_at TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  INDEX idx_inter_user (user_id, created_at),
  CONSTRAINT fk_inter_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS recommendation_logs (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  user_id INT NOT NULL,
  source VARCHAR(30) NOT NULL,
  context JSON NOT NULL,
  model_info JSON NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_rl_user (user_id, created_at),
  CONSTRAINT fk_rl_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS recommendation_items (
  log_id BIGINT NOT NULL,
  rank_pos SMALLINT NOT NULL,
  recipe_id INT NOT NULL,
  score DOUBLE NOT NULL,
  PRIMARY KEY (log_id, rank_pos),
  CONSTRAINT fk_ri_log FOREIGN KEY (log_id) REFERENCES recommendation_logs(id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS meal_plans (
  id INT AUTO_INCREMENT PRIMARY KEY,
  user_id INT NOT NULL,
  name VARCHAR(120) NOT NULL,
  start_date DATE NOT NULL,
  days TINYINT NOT NULL,
  targets JSON NOT NULL,
  summary JSON NOT NULL,
  narrative TEXT NULL,
  narrative_mode VARCHAR(20) NOT NULL DEFAULT 'template',
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_mp_user (user_id, created_at),
  CONSTRAINT fk_mp_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS meal_plan_items (
  id INT AUTO_INCREMENT PRIMARY KEY,
  plan_id INT NOT NULL,
  day_index TINYINT NOT NULL,
  slot VARCHAR(20) NOT NULL,
  recipe_id INT NOT NULL,
  servings DOUBLE NOT NULL,
  nutrition JSON NOT NULL,
  INDEX idx_mpi_plan (plan_id, day_index),
  CONSTRAINT fk_mpi_plan FOREIGN KEY (plan_id) REFERENCES meal_plans(id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS meal_logs (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  user_id INT NOT NULL,
  log_date DATE NOT NULL,
  slot VARCHAR(20) NOT NULL,
  item_type ENUM('recipe','food') NOT NULL,
  item_id VARCHAR(40) NOT NULL,
  item_name VARCHAR(255) NOT NULL,
  quantity DOUBLE NOT NULL,
  unit VARCHAR(20) NOT NULL,
  calories_kcal DOUBLE NULL,
  protein_g DOUBLE NULL,
  carbs_g DOUBLE NULL,
  fat_g DOUBLE NULL,
  fiber_g DOUBLE NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_ml_user_date (user_id, log_date),
  CONSTRAINT fk_ml_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS chat_messages (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  user_id INT NOT NULL,
  role ENUM('user','assistant') NOT NULL,
  content TEXT NOT NULL,
  meta JSON NULL,
  created_at TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  INDEX idx_chat_user (user_id, created_at),
  CONSTRAINT fk_chat_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS datasets (
  id INT AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(120) NOT NULL,
  original_filename VARCHAR(255) NOT NULL,
  stored_path VARCHAR(500) NOT NULL,
  file_format VARCHAR(20) NOT NULL,
  size_bytes BIGINT NOT NULL,
  status VARCHAR(20) NOT NULL DEFAULT 'registered',
  row_count BIGINT NULL,
  profile JSON NULL,
  cleaned_path VARCHAR(500) NULL,
  uploaded_by INT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS jobs (
  id INT AUTO_INCREMENT PRIMARY KEY,
  job_type VARCHAR(30) NOT NULL,
  dataset_id INT NULL,
  status ENUM('queued','running','succeeded','failed') NOT NULL DEFAULT 'queued',
  progress DOUBLE NOT NULL DEFAULT 0,
  message VARCHAR(255) NULL,
  result JSON NULL,
  error TEXT NULL,
  created_by INT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  started_at TIMESTAMP NULL,
  finished_at TIMESTAMP NULL,
  INDEX idx_jobs_created (created_at)
) ENGINE=InnoDB;
