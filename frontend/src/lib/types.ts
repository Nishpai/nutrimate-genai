export type Nutrients = {
  calories_kcal: number | null
  protein_g: number | null
  carbs_g: number | null
  fat_g: number | null
  fiber_g: number | null
}

export type User = { id: number; email: string; full_name: string; role: "user" | "admin"; onboarded: boolean }

export type Profile = {
  sex: "male" | "female" | null
  age: number | null
  height_cm: number | null
  weight_kg: number | null
  activity: string | null
  goal: "lose" | "maintain" | "gain" | null
  diet: "any" | "eggetarian" | "vegetarian" | "vegan"
  allergies: string[]
  restrictions: string[]
  cuisines: string[]
  calorie_target: number | null
  protein_target_g: number | null
  carbs_target_g: number | null
  fat_target_g: number | null
  fiber_target_g: number | null
  meals_per_day: number
  max_minutes: number | null
}

export type RecipeCard = Nutrients & {
  recipe_id: number
  name: string
  cuisine: string
  meal_type: string
  category: string
  total_minutes: number | null
  servings: number | null
  is_vegetarian: boolean
  is_vegan: boolean
  is_eggetarian: boolean
  allergens: string[]
  mean_rating: number | null
  n_ratings: number
  nutrition_status: string
}

export type RecItem = {
  recipe: RecipeCard
  score: number
  components: { content: number; cf: number; popularity: number; hybrid: number }
  reasons: string[]
  saved?: boolean
  breakfast_fallback?: boolean
}

export type RecResponse = {
  items: RecItem[]
  passed: number
  removed: Record<string, number>
  mode: string
  personalised: boolean
  applied_rules: string[]
  liked_count: number
  breakfast_note?: string
}

export type PlanMeal = {
  slot: string
  recipe: Partial<RecipeCard> & { recipe_id: number; name: string }
  servings: number
  nutrition: Nutrients
  reasons?: string[]
  added_to_reach_target?: boolean
  breakfast_fallback?: boolean
}

export type PlanDay = { day_index: number; date: string; meals: PlanMeal[]; totals: Nutrients; kcal_diff_pct?: number }

export type Plan = {
  id?: number
  name?: string
  days: PlanDay[]
  summary: {
    days: number
    target_kcal: number
    target_protein_g: number | null
    avg_kcal: number
    avg_protein_g: number
    max_abs_kcal_diff_pct: number
    days_within_10pct: number
  }
  rules?: string[]
  narrative?: string | null
  narrative_mode?: string
  start_date?: string
  breakfast_note?: string
}
