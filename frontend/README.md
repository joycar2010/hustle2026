# Hustle XAU Frontend

Modern, responsive web interface for the Hustle XAU Arbitrage Trading System.

## Tech Stack

- **Framework**: Vue 3 (Composition API)
- **Build Tool**: Vite
- **Styling**: TailwindCSS
- **State Management**: Pinia
- **HTTP Client**: Axios
- **Charts**: Chart.js + vue-chartjs
- **WebSocket**: Socket.IO Client
- **Date Handling**: Day.js

## Features

### 📱 Responsive Design
- **Desktop**: Full-featured trading interface with multi-panel layout
- **Tablet**: Optimized layout with collapsible panels
- **Mobile H5**: Touch-friendly interface with bottom navigation

### 🎨 UI Components
- Dark theme inspired by modern crypto exchanges
- Real-time market data display
- Interactive order book
- Trading chart (placeholder for Chart.js integration)
- Order entry forms
- Position management tables
- Risk control dashboard

### 🔐 Authentication
- JWT-based authentication
- Secure token storage
- Auto-redirect on session expiry
- Protected routes

### 📊 Key Pages

#### 1. Dashboard
- Account balance overview
- Open positions summary
- Today's P&L
- Running strategies count
- Market overview
- Recent activity feed

#### 2. Trading
- Real-time market data
- Order book (bids/asks)
- Trading chart
- Forward/Reverse arbitrage forms
- Account selection
- Open orders table

#### 3. Strategies
- List of automated strategies
- Start/Stop strategy controls
- Strategy configuration
- Performance metrics

#### 4. Positions
- Open positions table
- Real-time P&L updates
- Position close functionality
- Duration tracking

#### 5. Accounts
- Binance accounts list
- Bybit MT5 accounts list
- Account balances
- Active/Inactive status

#### 6. Risk Control
- Emergency stop button
- Risk metrics dashboard
- Active alerts
- MT5 status monitoring

## Installation

### Prerequisites
- Node.js 18+
- npm or yarn

### Setup

1. Install dependencies:
```bash
cd frontend
npm install
```

2. Create environment file:
```bash
cp .env.example .env
```

3. Configure environment variables:
```env
VITE_API_BASE_URL=http://localhost:8000
VITE_WS_URL=ws://localhost:8000
```

4. Start development server:
```bash
npm run dev
```

The app will be available at `http://localhost:3000`

## Development

### Project Structure

```
frontend/
├── src/
│   ├── assets/          # Static assets, CSS
│   ├── components/      # Reusable components
│   │   ├── trading/     # Trading-specific components
│   │   └── Navbar.vue   # Navigation bar
│   ├── views/           # Page components
│   │   ├── Dashboard.vue
│   │   ├── Trading.vue
│   │   ├── Strategies.vue
│   │   ├── Positions.vue
│   │   ├── Accounts.vue
│   │   ├── Risk.vue
│   │   └── Login.vue
│   ├── stores/          # Pinia stores
│   │   ├── auth.js      # Authentication state
│   │   └── market.js    # Market data state
│   ├── services/        # API services
│   │   └── api.js       # Axios instance
│   ├── router/          # Vue Router
│   │   └── index.js
│   ├── App.vue          # Root component
│   └── main.js          # Entry point
├── index.html
├── package.json
├── vite.config.js
├── tailwind.config.js
└── postcss.config.js
```

### Key Components

#### Navbar.vue
- Responsive navigation
- User info display
- Mobile menu toggle
- Logout functionality

#### Trading Components
- **OrderBook.vue**: Real-time order book display
- **TradingChart.vue**: Price chart (placeholder)
- **TradingForm.vue**: Arbitrage execution form
- **RecentTrades.vue**: Recent trades list
- **OpenOrders.vue**: Open orders table

### State Management

#### Auth Store (`stores/auth.js`)
```javascript
- token: JWT token
- user: User object
- isAuthenticated: Computed property
- login(username, password): Login method
- logout(): Logout method
- fetchUser(): Fetch user data
```

#### Market Store (`stores/market.js`)
```javascript
- marketData: Current market data
- orderBook: Order book data
- recentTrades: Recent trades
- fetchMarketData(symbol): Fetch market data
- fetchOrderBook(symbol): Fetch order book
```

### API Integration

All API calls go through the Axios instance in `services/api.js`:

```javascript
// Automatic token injection
api.get('/api/v1/endpoint')

// Automatic 401 handling
// Redirects to login on unauthorized
```

### Styling

#### TailwindCSS Custom Theme

```javascript
colors: {
  primary: '#F0B90B',      // Gold/Yellow
  dark: {
    100: '#1E2329',        // Card background
    200: '#181A20',        // Input background
    300: '#0B0E11',        // Page background
  },
  green: {
    500: '#0ECB81',        // Buy/Profit
  },
  red: {
    500: '#F6465D',        // Sell/Loss
  },
}
```

#### Custom CSS Classes

```css
.btn-primary    - Primary button (gold)
.btn-buy        - Buy button (green)
.btn-sell       - Sell button (red)
.card           - Card container
.input-field    - Form input
```

## Building for Production

```bash
npm run build
```

Output will be in `dist/` directory.

### Preview Production Build

```bash
npm run preview
```

## Responsive Breakpoints

- **Mobile**: < 768px
- **Tablet**: 768px - 1024px
- **Desktop**: > 1024px

### Mobile Optimizations

- Bottom navigation bar
- Collapsible sections
- Touch-friendly buttons
- Simplified layouts
- Swipeable panels

## WebSocket Integration

Real-time updates via Socket.IO:

```javascript
import { io } from 'socket.io-client'

const socket = io('ws://localhost:8000')

socket.on('market_data', (data) => {
  // Update market data
})

socket.on('risk_alert', (alert) => {
  // Show risk alert
})
```

## API Endpoints Used

### Authentication
- `POST /api/v1/auth/login` - Login
- `GET /api/v1/users/me` - Get current user

### Market Data
- `GET /api/v1/market/data/:symbol` - Get market data
- `GET /api/v1/market/orderbook/:symbol` - Get order book

### Trading
- `POST /api/v1/strategies/execute` - Execute arbitrage
- `GET /api/v1/strategies/tasks` - Get tasks
- `POST /api/v1/strategies/tasks/:id/close` - Close position

### Strategies
- `GET /api/v1/strategies` - List strategies
- `POST /api/v1/automation/strategies/:id/start` - Start strategy
- `POST /api/v1/automation/strategies/:id/stop` - Stop strategy

### Accounts
- `GET /api/v1/accounts` - List accounts
- `GET /api/v1/accounts/:id/balance` - Get balance

### Risk Control
- `GET /api/v1/risk/status` - Get risk status
- `POST /api/v1/risk/emergency-stop/activate` - Activate emergency stop
- `POST /api/v1/risk/emergency-stop/deactivate` - Deactivate emergency stop

## Future Enhancements

### Phase 1 (Completed)
- ✅ Basic UI structure
- ✅ Authentication
- ✅ Dashboard
- ✅ Trading interface
- ✅ Responsive design

### Phase 2 (Planned)
- [ ] Real-time WebSocket integration
- [ ] Trading chart with Chart.js
- [ ] Advanced order types
- [ ] Position history
- [ ] Performance analytics

### Phase 3 (Planned)
- [ ] Strategy backtesting UI
- [ ] Risk analytics dashboard
- [ ] Multi-language support
- [ ] Dark/Light theme toggle
- [ ] Mobile app (React Native)

## Troubleshooting

### CORS Issues
Ensure backend CORS is configured:
```python
# backend/app/main.py
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

### API Connection
Check Vite proxy configuration in `vite.config.js`:
```javascript
server: {
  proxy: {
    '/api': 'http://localhost:8000',
  },
}
```

### Build Errors
Clear node_modules and reinstall:
```bash
rm -rf node_modules package-lock.json
npm install
```

## License

Proprietary - All rights reserved

## Support

For issues or questions, refer to the main project documentation.
