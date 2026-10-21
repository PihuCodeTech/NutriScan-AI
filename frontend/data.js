// NutriScan AI web: sample data, built-in recipes, badges, and the helpers that work without a server.
// Load order in index.html: config.js, data.js, api.js, auth.js, app.js

// ---------- Street-food detector ----------
// Used when the server does not say whether a food is street food, and for meals typed by hand.
const STREET_WORDS = new RegExp([
  'samosa', 'kachori', 'kachauri', 'pakora', 'pakoda', 'bhajiya', 'bhajji', 'bhaji', 'vada ?pav', 'pani ?puri',
  'golgappa', 'gol gappa', 'puchka', 'chaat', 'bhel', 'sev ?puri', 'dahi ?puri', 'papdi', 'tikki', 'momo',
  'chow ?mein', 'hakka', 'burger', 'shawarma', 'kathi', 'frankie', '\\brolls?\\b', 'french fries', '\\bfries\\b',
  'jalebi', 'imarti', 'fried rice', 'bhature', 'kulche', 'pav ?bhaji', 'street',
].join('|'), 'i');

const isStreetFood = name => STREET_WORDS.test(String(name || ''));

// ---------- Sample foods ----------
// The first three are also the guest sample meals on the dashboard (foods[0] is the street meal).
// When no server answers, a scan returns one of these (label mode always returns the noodle pack).
const foods = [
  {
    name: 'Samosa (2 pieces)', cal: 520, protein: 8, carbs: 52, fat: 30, fibre: 4, sodium: 615, sugar: 2, street: true,
    summary: 'Deep-fried pastry filled with spiced potato and peas. Stalls often fry in oil that has been used many times.',
    pros: ['Potato and peas give quick energy', 'The filling adds a little protein and fibre'],
    cons: ['Deep-fried, so high in fat', 'Refined flour pastry with little fibre', 'Reused frying oil at street stalls'],
    ingredients: [{ name: 'Refined wheat flour', risk: 'medium' }, { name: 'Frying oil', risk: 'high' }, { name: 'Potato', risk: 'low' }, { name: 'Peas', risk: 'low' }, { name: 'Spices', risk: 'low' }],
  },
  {
    name: 'Rajma chawal (1 plate)', cal: 480, protein: 16, carbs: 78, fat: 10, fibre: 9, sodium: 480, sugar: 5, street: false,
    summary: 'Kidney beans in tomato gravy with rice. A balanced home-style plate with plant protein and fibre.',
    pros: ['Rajma gives plant protein and fibre', 'Low in fat when cooked with little oil', 'Keeps you full for hours'],
    cons: ['A large rice portion pushes carbs up', 'Restaurant versions use more oil and salt'],
    ingredients: [{ name: 'Kidney beans', risk: 'low' }, { name: 'Rice', risk: 'low' }, { name: 'Onion and tomato gravy', risk: 'low' }, { name: 'Cooking oil', risk: 'low' }],
  },
  {
    name: 'Instant noodles (1 pack)', cal: 380, protein: 8, carbs: 54, fat: 14, fibre: 2, sodium: 1500, sugar: 3, street: false,
    summary: 'Packaged noodles with a seasoning sachet. Label shows a very high sodium value.',
    pros: ['Quick to make'],
    cons: ['Sodium close to a full day\'s limit', 'Refined flour, little fibre', 'Hard on kidneys if eaten often'],
    ingredients: [{ name: 'Refined wheat flour', risk: 'medium' }, { name: 'Palm oil', risk: 'medium' }, { name: 'Salt', risk: 'high' }, { name: 'Flavour enhancers', risk: 'medium' }, { name: 'Sugar', risk: 'low' }],
  },
  {
    name: 'Veg momos (6 pieces)', cal: 280, protein: 9, carbs: 42, fat: 8, fibre: 3, sodium: 620, sugar: 3, street: true,
    summary: 'Steamed dumplings with a cabbage filling, served with a spicy red chutney and often a mayonnaise dip.',
    pros: ['Steamed, not fried', 'Moderate calories for a snack'],
    cons: ['Refined flour wrappers', 'Chutney and mayo add salt and fat', 'Street hygiene varies'],
    ingredients: [{ name: 'Refined wheat flour', risk: 'medium' }, { name: 'Cabbage', risk: 'low' }, { name: 'Mayonnaise', risk: 'medium' }, { name: 'Red chilli chutney', risk: 'medium' }],
  },
  {
    name: 'Masala dosa with sambar', cal: 420, protein: 9, carbs: 62, fat: 15, fibre: 5, sodium: 640, sugar: 4, street: false,
    summary: 'A fermented rice and lentil crepe with a potato filling, and a lentil and vegetable stew on the side.',
    pros: ['Fermented batter is easier to digest', 'Sambar adds lentils and vegetables'],
    cons: ['Restaurant dosas are cooked in a lot of oil', 'Potato filling is starchy'],
    ingredients: [{ name: 'Rice and urad dal batter', risk: 'low' }, { name: 'Potato', risk: 'low' }, { name: 'Cooking oil', risk: 'medium' }, { name: 'Sambar', risk: 'low' }],
  },
  {
    name: 'Chole bhature (1 plate)', cal: 650, protein: 17, carbs: 78, fat: 30, fibre: 10, sodium: 900, sugar: 6, street: true,
    summary: 'Spiced chickpeas with deep-fried bread. Very filling and very heavy.',
    pros: ['Chickpeas give protein and fibre'],
    cons: ['Bhature are deep-fried and high in fat', 'Over a quarter of a day\'s calories in one plate', 'Refined flour dough'],
    ingredients: [{ name: 'Chickpeas', risk: 'low' }, { name: 'Refined wheat flour', risk: 'medium' }, { name: 'Frying oil', risk: 'high' }, { name: 'Salt', risk: 'medium' }],
  },
];

// ---------- Levels, kitchens, diets ----------
const LEVELS = ['Newcomer', 'Mess regular', 'Home cook', 'Streak keeper', 'Kitchen pro', 'Health champion'];

// Every badge stays unlocked once earned. Streak badges must have ids that start with "s" (the rewards page relies on it).
const BADGES = [
  { id: 'f1', name: 'First scan', icon: 'camera', desc: 'Scan your first meal or label', goal: 1, of: c => c.scans, test: c => c.scans >= 1 },
  { id: 's3', name: '3-day streak', icon: 'sprout', desc: 'Go 3 days without street food', goal: 3, of: c => c.streak, test: c => c.streak >= 3 },
  { id: 's7', name: '7-day streak', icon: 'flame', desc: 'Go a full week without street food', goal: 7, of: c => c.streak, test: c => c.streak >= 7 },
  { id: 's14', name: '14-day streak', icon: 'trophy', desc: 'Go two weeks without street food', goal: 14, of: c => c.streak, test: c => c.streak >= 14 },
  { id: 'h1', name: 'First swap', icon: 'cook', desc: 'Cook a home swap and log it', goal: 1, of: c => c.home, test: c => c.home >= 1 },
  { id: 'l1', name: 'Label reader', icon: 'tag', desc: 'Scan a product label', goal: 1, of: c => c.labelScans, test: c => c.labelScans >= 1 },
];

const KITCHENS = { none: 'No cooking', kettle: 'Kettle only', burner: 'Induction or gas burner' };
const KITCHEN_RANK = { none: 0, kettle: 1, burner: 2 };
// A higher number eats more kinds of food. A recipe is usable when its rank is at or below the person's.
const DIET_RANK = { Vegan: 0, Vegetarian: 1, Eggetarian: 2, 'Non-vegetarian': 3 };

const PANTRY_CHIPS = ['poha', 'oats', 'eggs', 'bread', 'curd', 'onion', 'tomato', 'peanuts', 'paneer', 'sprouts', 'besan', 'rice', 'dal', 'banana'];

// ---------- 12 home-cooked recipes ----------
// keys: words in a street-food name that this recipe is a good swap for (lower case).
// pantry: the main ingredients (salt, oil, spices and lemon are assumed). Used to match "what is in my room".
// gear: none (no cooking), kettle (hot water only) or burner.
const RECIPES = [
  {
    id: 'cutlet', meal: 'Veg cutlet on the tawa with mint curd', from: 'Samosa / kachori / pakora',
    keys: ['samosa', 'kachori', 'kachauri', 'pakora', 'pakoda'], diet: 'Vegetarian', gear: 'burner', time: 25,
    cal: 210, protein: 9, carbs: 26, fat: 8, fibre: 5, sodium: 320, sugar: 3,
    why: 'Shallow-cooked with a teaspoon of oil instead of deep-fried, and the curd adds probiotics.',
    pantry: ['potato', 'peas', 'carrot', 'curd', 'mint'],
    steps: [
      'Boil 2 potatoes, a handful of peas and a chopped carrot until soft, then mash them together.',
      'Mix in chopped mint, 1 tsp cumin powder, salt and a spoon of oats or bread crumbs so it holds together.',
      'Shape the mix into flat cutlets.',
      'Heat a tawa with 1 tsp oil and cook the cutlets 3 to 4 minutes on each side until golden.',
      'Whisk curd with mint and a pinch of salt and serve it on the side.',
    ],
  },
  {
    id: 'dumplings', meal: 'Steamed veg dumplings with home chutney', from: 'Momos / chowmein',
    keys: ['momo', 'chowmein', 'chow mein', 'hakka'], diet: 'Vegan', gear: 'burner', time: 30,
    cal: 220, protein: 8, carbs: 36, fat: 5, fibre: 5, sodium: 380, sugar: 3,
    why: 'Steamed instead of fried, with whole wheat wrappers and no mayo.',
    pantry: ['whole wheat flour', 'cabbage', 'carrot', 'garlic', 'tomato'],
    steps: [
      'Knead 1 cup whole wheat flour with water into a soft dough and rest it for 10 minutes.',
      'Grate cabbage and carrot, then sauté them with chopped garlic and salt for 2 minutes.',
      'Roll the dough into small circles, add a spoon of filling to each and pinch them shut.',
      'Steam the dumplings in a pot with a plate or steamer for 10 to 12 minutes.',
      'Blend tomato, garlic, a red chilli and salt into a quick chutney.',
    ],
  },
  {
    id: 'sprout-chaat', meal: 'Sprout chaat with lemon and onion', from: 'Pani puri / chaat / bhel',
    keys: ['pani puri', 'panipuri', 'golgappa', 'gol gappa', 'puchka', 'chaat', 'bhel', 'sev puri', 'dahi puri'], diet: 'Vegan', gear: 'none', time: 10,
    cal: 180, protein: 12, carbs: 26, fat: 3, fibre: 8, sodium: 210, sugar: 4,
    why: 'Plenty of protein and fibre, and no fried shells.',
    pantry: ['sprout', 'onion', 'tomato'],
    steps: [
      'Take 1 cup of ready sprouts. Or soak moong overnight and keep it in a damp cloth until it sprouts.',
      'Mix in chopped onion and tomato.',
      'Add lemon juice, chaat masala, salt and chopped coriander.',
      'Eat it straight away so it stays crunchy.',
    ],
  },
  {
    id: 'wrap', meal: 'Paneer and veg whole wheat wrap', from: 'Burger / roll / shawarma',
    keys: ['burger', 'roll', 'shawarma', 'frankie', 'kathi'], diet: 'Vegetarian', gear: 'burner', time: 15,
    cal: 320, protein: 17, carbs: 34, fat: 13, fibre: 6, sodium: 420, sugar: 4,
    why: 'The same handheld meal with real protein and fibre.',
    pantry: ['paneer', 'roti', 'onion', 'capsicum', 'curd'],
    steps: [
      'Cut 80 g paneer into small cubes and sauté with sliced onion and capsicum, salt and chilli powder for 5 minutes.',
      'Warm a whole wheat roti on the tawa.',
      'Spread a spoon of curd on the roti and add the paneer mix.',
      'Roll it tight and cut it in half.',
    ],
  },
  {
    id: 'poha', meal: 'Veg poha with peanuts', from: 'Maggi / instant noodles / vada pav',
    keys: ['maggi', 'instant noodle', 'noodle', 'vada pav', 'vadapav'], diet: 'Vegan', gear: 'burner', time: 15,
    cal: 300, protein: 9, carbs: 46, fat: 9, fibre: 4, sodium: 280, sugar: 3,
    why: 'Lower sodium than a noodle packet and just as quick.',
    pantry: ['poha', 'onion', 'peanut', 'tomato'],
    steps: [
      'Rinse 1 cup poha in a sieve until soft, then drain it.',
      'Heat 1 tsp oil and fry a handful of peanuts for 1 minute.',
      'Add mustard seeds, chopped onion and tomato and cook until soft. Stir in turmeric and salt.',
      'Add the poha and mix for 2 minutes.',
      'Finish with lemon juice and coriander.',
    ],
  },
  {
    id: 'kettle-oats', meal: 'Kettle masala oats with peanuts', from: 'Maggi / instant noodles',
    keys: ['maggi', 'instant noodle', 'noodle'], diet: 'Vegan', gear: 'kettle', time: 10,
    cal: 260, protein: 10, carbs: 38, fat: 8, fibre: 6, sodium: 290, sugar: 2,
    why: 'Only needs hot water from a kettle, and has about a fifth of the sodium of a noodle pack.',
    pantry: ['oat', 'peanut', 'onion', 'tomato'],
    steps: [
      'Put half a cup of oats, chopped onion and tomato, a handful of roasted peanuts, half a teaspoon of masala and a pinch of salt in a big bowl.',
      'Pour in hot water from the kettle until the oats are just covered.',
      'Cover the bowl and leave it for 4 minutes.',
      'Stir, add a squeeze of lemon and eat it hot.',
    ],
  },
  {
    id: 'khichdi', meal: 'One-pot dal khichdi', from: 'Fried rice / heavy street meals',
    keys: ['fried rice', 'schezwan', 'biryani', 'bhature', 'kulche'], diet: 'Vegan', gear: 'burner', time: 25,
    cal: 340, protein: 14, carbs: 58, fat: 6, fibre: 9, sodium: 300, sugar: 2,
    why: 'Easy on the stomach, high in fibre, and it all cooks in one pot.',
    pantry: ['rice', 'dal', 'tomato', 'peas'],
    steps: [
      'Wash half a cup of rice and half a cup of moong dal together.',
      'Put them in a pot or cooker with 3 cups of water, turmeric, salt, chopped tomato and a handful of peas.',
      'Cook until everything is soft: about 3 whistles in a cooker or 20 minutes in a pot.',
      'Heat 1 tsp oil with cumin seeds for a few seconds and pour it over the top.',
    ],
  },
  {
    id: 'chilla', meal: 'Besan chilla with curd', from: 'Pakora / bhajiya / vada pav',
    keys: ['pakora', 'pakoda', 'bhajiya', 'bhajji', 'bhaji', 'vada pav', 'vadapav'], diet: 'Vegetarian', gear: 'burner', time: 15,
    cal: 230, protein: 14, carbs: 26, fat: 8, fibre: 6, sodium: 260, sugar: 4,
    why: 'Same gram-flour taste, pan-cooked instead of deep-fried, with far more protein.',
    pantry: ['besan', 'onion', 'tomato', 'curd'],
    steps: [
      'Whisk half a cup of besan with water into a pourable batter. Add salt and a pinch of turmeric.',
      'Stir in chopped onion, tomato and coriander.',
      'Pour a ladle onto a lightly oiled tawa and spread it thin like a pancake.',
      'Cook 2 to 3 minutes on each side until golden. Serve with curd.',
    ],
  },
  {
    id: 'bhel', meal: 'Roasted chana and peanut bhel', from: 'Fries / chips / puffs / bhel',
    keys: ['fries', 'french fries', 'chips', 'puff', 'kurkure', 'bhel', 'namkeen'], diet: 'Vegan', gear: 'none', time: 5,
    cal: 240, protein: 12, carbs: 28, fat: 8, fibre: 9, sodium: 200, sugar: 3,
    why: 'A no-cook crunchy snack that keeps you full.',
    pantry: ['chana', 'peanut', 'onion', 'tomato'],
    steps: [
      'Mix half a cup of roasted chana and a handful of roasted peanuts in a bowl.',
      'Add chopped onion and tomato.',
      'Squeeze in lemon juice and add chaat masala, salt and coriander.',
      'Eat right away so it stays crisp.',
    ],
  },
  {
    id: 'pb-toast', meal: 'Banana and peanut butter toast', from: 'Jalebi / sweets',
    keys: ['jalebi', 'imarti', 'sweet', 'mithai', 'gulab jamun', 'halwai'], diet: 'Vegan', gear: 'none', time: 5,
    cal: 290, protein: 9, carbs: 38, fat: 12, fibre: 5, sodium: 190, sugar: 14,
    why: 'Sweet taste from fruit, with protein and fat to slow the sugar down.',
    pantry: ['bread', 'banana', 'peanut butter'],
    steps: [
      'Spread 1 tablespoon of peanut butter over 2 slices of bread.',
      'Slice a banana and lay it on top.',
      'Add a pinch of cinnamon if you have it.',
    ],
  },
  {
    id: 'egg-bhurji', meal: 'Egg bhurji on whole wheat toast', from: 'Egg roll / omelette stall',
    keys: ['egg', 'omelette', 'omelet', 'anda'], diet: 'Eggetarian', gear: 'burner', time: 10,
    cal: 280, protein: 18, carbs: 20, fat: 14, fibre: 3, sodium: 380, sugar: 2,
    why: 'The same eggs as the roll stall, with vegetables and one teaspoon of oil.',
    pantry: ['egg', 'onion', 'tomato', 'bread'],
    steps: [
      'Whisk 2 eggs with a pinch of salt.',
      'Heat 1 tsp oil and cook chopped onion, tomato and a green chilli for 2 minutes. Stir in turmeric.',
      'Pour in the eggs and stir until they are just set.',
      'Serve on 2 slices of toast, whole wheat if you can.',
    ],
  },
  {
    id: 'chicken-bowl', meal: 'Chicken and veg rice bowl', from: 'Chicken roll / tandoori / chicken fried rice',
    keys: ['chicken', 'tandoori', 'kebab'], diet: 'Non-vegetarian', gear: 'burner', time: 30,
    cal: 420, protein: 32, carbs: 46, fat: 10, fibre: 5, sodium: 480, sugar: 3,
    why: 'Lean protein and vegetables cooked in little oil, with no sauce packets or reused frying oil.',
    pantry: ['chicken', 'rice', 'onion', 'carrot', 'peas'],
    steps: [
      'Cook 1 cup of rice and keep it warm.',
      'Heat 1 tsp oil and cook chopped onion until soft.',
      'Add 150 g chicken pieces with turmeric, chilli powder and salt. Cover and cook 10 minutes, until no pink is left inside.',
      'Add diced carrot and peas and cook 5 more minutes.',
      'Serve over the rice.',
    ],
  },
];

// Recipes this person can make: their diet allows it and their kitchen has the gear.
function usableRecipes(p) {
  const diet = DIET_RANK[p.diet] ?? DIET_RANK.Vegetarian, kit = KITCHEN_RANK[p.kitchen] ?? KITCHEN_RANK.burner;
  return RECIPES.filter(r => DIET_RANK[r.diet] <= diet && KITCHEN_RANK[r.gear] <= kit);
}

// ---------- "What is in my room?" matching ----------
// Turns "Peanuts", "2 eggs" or "yogurt" into a comparable form: lower case, singular, one common name.
const stem = w => {
  w = String(w ?? '').toLowerCase().trim().replace(/\s+/g, ' ');
  if (w.length > 3) {
    if (/ies$/.test(w)) w = w.slice(0, -3) + 'y';
    else if (/(oes|ches|shes|sses)$/.test(w)) w = w.slice(0, -2);
    else if (/[^s]s$/.test(w)) w = w.slice(0, -1);
  }
  return w;
};

const SYNONYMS = {
  yogurt: 'curd', yoghurt: 'curd', dahi: 'curd', 'flattened rice': 'poha', pohe: 'poha', aval: 'poha', avalakki: 'poha',
  'gram flour': 'besan', 'chickpea flour': 'besan', chickpea: 'chana', chole: 'chana', 'kabuli chana': 'chana', 'kala chana': 'chana',
  'black chana': 'chana', 'roasted chana': 'chana', atta: 'whole wheat flour', 'wheat flour': 'whole wheat flour',
  chapati: 'roti', chapatti: 'roti', phulka: 'roti', tortilla: 'roti', oatmeal: 'oat', sprouted: 'sprout',
  lentil: 'dal', masoor: 'dal', toor: 'dal', arhar: 'dal', groundnut: 'peanut', moongfali: 'peanut', 'peanut butter': 'peanut-butter',
  'cottage cheese': 'paneer', aloo: 'potato', matar: 'pea', 'bell pepper': 'capsicum', 'shimla mirch': 'capsicum', pudina: 'mint',
};
const SYNONYM_RULES = Object.entries(SYNONYMS).sort((a, b) => b[0].length - a[0].length).map(([k, v]) => [new RegExp('\\b' + k + '\\b', 'g'), v]);
const canon = x => { let s = stem(x); for (const [re, v] of SYNONYM_RULES) s = s.replace(re, v); return s; };

// One comma-separated input turned into a list of comparable items.
const ingredientTokens = text => String(text ?? '').split(/,|\n|;/).map(stem).filter(Boolean);

// "green pea" covers a recipe that needs "pea"; "peanut" does not cover "peanut butter".
const sameIngredient = (have, need) => have === need || (' ' + have + ' ').includes(' ' + need + ' ');

// Picks up to five built-in recipes that use at least half of what the person has listed as main ingredients.
function localSuggest(items, profile) {
  const have = items.map(canon).filter(Boolean);
  if (!have.length) return [];
  return usableRecipes(profile)
    .map(r => {
      const got = r.pantry.filter(n => have.some(h => sameIngredient(h, canon(n))));
      return { r, missing: r.pantry.filter(n => !got.includes(n)), score: got.length / r.pantry.length, got: got.length };
    })
    .filter(x => x.got >= 1 && x.score >= 0.5)
    .sort((a, b) => b.score - a.score || a.missing.length - b.missing.length || a.r.time - b.r.time)
    .slice(0, 5)
    .map(x => ({
      ...x.r, from: '',
      why: x.r.why + (x.missing.length ? ' You still need: ' + x.missing.join(', ') + '.' : ' You have everything for it.'),
    }));
}
