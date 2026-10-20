import { useEffect, useState } from 'react'
import './App.css'

function LoginScreen({
  username,
  setUsername,
  password,
  setPassword,
  error,
  isSubmitting,
  onSubmit,
}) {
  return (
    <main className="auth-page">
      <form className="auth-card" onSubmit={onSubmit}>
        <h1>Wellnest</h1>
        <p>Sign in to your pharmacy inventory</p>
        <label>
          Username
          <input
            type="text"
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            autoComplete="username"
            required
          />
        </label>
        <label>
          Password
          <input
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            autoComplete="current-password"
            required
          />
        </label>
        {error && <p className="auth-error" role="alert">{error}</p>}
        <button type="submit" disabled={isSubmitting}>
          {isSubmitting ? 'Signing in…' : 'Sign in'}
        </button>
      </form>
    </main>
  )
}

const medicines = [
  {
    sku: 'MED-0001',
    name: 'Paracetamol 500mg',
    category: 'Pain relief',
    batch: 'PCM-2408A',
    quantity: 248,
    reorderLevel: 30,
    expiry: '2027-08-18',
    purchaseCost: 500,
    sellingPrice: 1000,
  },
  {
    sku: 'MED-0002',
    name: 'Amoxicillin 250mg',
    category: 'Antibiotics',
    batch: 'AMX-2503B',
    quantity: 18,
    reorderLevel: 25,
    expiry: '2027-02-03',
    purchaseCost: 800,
    sellingPrice: 1600,
  },
  {
    sku: 'MED-0004',
    name: 'ORS Sachets',
    category: 'Rehydration',
    batch: 'ORS-2412C',
    quantity: 7,
    reorderLevel: 10,
    expiry: '2027-01-12',
    purchaseCost: 300,
    sellingPrice: 600,
  },
  {
    sku: 'MED-0006',
    name: 'Artemether/Lumefantrine',
    category: 'Antimalarials',
    batch: 'AL-2403D',
    quantity: 0,
    reorderLevel: 20,
    expiry: '2027-03-08',
    purchaseCost: 1200,
    sellingPrice: 2400,
  },
]

const emptyBatch = {
  sku: '',
  name: '',
  category: '',
  batch: '',
  quantity: '',
  reorderLevel: '',
  expiry: '',
  supplier: '',
  reference: '',
  purchaseCost: '',
  sellingPrice: '',
}

const emptyDispense = {
  sku: '',
  transactionType: 'Sale',
  quantity: '',
  recipient: '',
  reference: '',
  amountReceived: '',
  paymentMethod: '',
}

const emptyStockCount = {
  batch: '',
  quantity: '',
  reason: '',
  reference: '',
}

const emptySupplierInvoice = {
  supplier: '',
  invoiceNumber: '',
  invoiceAmount: '',
  amountPaid: '0',
  dueDate: '',
}

const emptySupplierPayment = {
  invoiceId: '',
  amount: '',
  method: '',
  reference: '',
}

const emptyCustomerPayment = {
  saleId: '',
  amount: '',
  method: '',
  reference: '',
}

function getStockStatus(medicine) {
  const today = new Date()
  today.setHours(0, 0, 0, 0)

  const expiryDate = new Date(`${medicine.expiry}T00:00:00`)

  if (expiryDate < today) return 'Expired'
  if (medicine.quantity === 0) return 'Out of stock'
  if (medicine.quantity <= medicine.reorderLevel) return 'Low stock'
  return 'In stock'
}


function getSupplierInvoiceStatus(invoice) {
  const balance = invoice.invoiceAmount - invoice.amountPaid
  const today = new Date().toISOString().slice(0, 10)

  if (balance <= 0) return 'Paid'
  if (invoice.dueDate && invoice.dueDate < today) return 'Overdue'
  if (invoice.amountPaid > 0) return 'Partially paid'
  return 'Unpaid'
}

function getSalePaymentStatus(sale) {
  if (sale.balanceDue <= 0) return 'Paid'
  if (sale.amountReceived > 0) return 'Partially paid'
  return 'Unpaid'
}

function App() {
  const [activePage, setActivePage] = useState('Overview')
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false)
  const [searchTerm, setSearchTerm] = useState('')
  const [statusFilter, setStatusFilter] = useState('all')
  const [inventory, setInventory] = useState(medicines)
  const [showAddForm, setShowAddForm] = useState(false)
  const [newBatch, setNewBatch] = useState(emptyBatch)
  const [formError, setFormError] = useState('')
  const [stockMovements, setStockMovements] = useState([])
  const [showDispenseForm, setShowDispenseForm] = useState(false)
  const [dispenseForm, setDispenseForm] = useState(emptyDispense)
  const [dispenseError, setDispenseError] = useState('')
  const [showStockCountForm, setShowStockCountForm] = useState(false)
  const [stockCountForm, setStockCountForm] = useState(emptyStockCount)
  const [stockCountError, setStockCountError] = useState('')
  const [sales, setSales] = useState([])
  const [supplierInvoices, setSupplierInvoices] = useState([])
  const [supplierPayments, setSupplierPayments] = useState([])
  const [showSupplierInvoiceForm, setShowSupplierInvoiceForm] = useState(false)
  const [supplierInvoiceForm, setSupplierInvoiceForm] = useState(emptySupplierInvoice)
  const [supplierInvoiceError, setSupplierInvoiceError] = useState('')
  const [showSupplierPaymentForm, setShowSupplierPaymentForm] = useState(false)
  const [supplierPaymentForm, setSupplierPaymentForm] = useState(emptySupplierPayment)
  const [supplierPaymentError, setSupplierPaymentError] = useState('')
  const [customerPayments, setCustomerPayments] = useState([])
  const [showCustomerPaymentForm, setShowCustomerPaymentForm] = useState(false)
  const [customerPaymentForm, setCustomerPaymentForm] = useState(emptyCustomerPayment)
  const [customerPaymentError, setCustomerPaymentError] = useState('')
  const [currentUser, setCurrentUser] = useState(null)
  const [authLoading, setAuthLoading] = useState(true)
  const [authError, setAuthError] = useState('')
  const [loginUsername, setLoginUsername] = useState('')
  const [loginPassword, setLoginPassword] = useState('')
  const [loginSubmitting, setLoginSubmitting] = useState(false)

  useEffect(() => {
    let cancelled = false

    async function restoreSession() {
      try {
        const response = await fetch('/api/auth/me/', {
          credentials: 'include',
        })

        if (response.status === 401) return

        const data = await response.json()
        if (!response.ok) {
          throw new Error(data.detail || 'Could not check your sign-in.')
        }

        if (!cancelled) setCurrentUser(data.user)
      } catch {
        if (!cancelled) {
          setAuthError('Could not reach the server. Check that Django is running.')
        }
      } finally {
        if (!cancelled) setAuthLoading(false)
      }
    }

    restoreSession()
    return () => {
      cancelled = true
    }
  }, [])

  async function handleLogin(event) {
    event.preventDefault()
    setAuthError('')
    setLoginSubmitting(true)

    try {
      const csrfResponse = await fetch('/api/auth/csrf/', {
        credentials: 'include',
      })
      const csrfData = await csrfResponse.json()

      if (!csrfResponse.ok) {
        throw new Error(csrfData.detail || 'Could not prepare secure sign-in.')
      }

      const response = await fetch('/api/auth/login/', {
        method: 'POST',
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': csrfData.csrfToken,
        },
        body: JSON.stringify({
          username: loginUsername,
          password: loginPassword,
        }),
      })
      const data = await response.json()

      if (!response.ok) {
        throw new Error(data.detail || 'Sign-in failed.')
      }

      setCurrentUser(data.user)
      setLoginPassword('')
    } catch (error) {
      setAuthError(error.message || 'Sign-in failed. Please try again.')
    } finally {
      setLoginSubmitting(false)
    }
  }

  async function handleLogout() {
    setAuthError('')

    try {
      const csrfResponse = await fetch('/api/auth/csrf/', {
        credentials: 'include',
      })
      const csrfData = await csrfResponse.json()

      const response = await fetch('/api/auth/logout/', {
        method: 'POST',
        credentials: 'include',
        headers: {
          'X-CSRFToken': csrfData.csrfToken,
        },
      })
      const data = await response.json()

      if (!response.ok) {
        throw new Error(data.detail || 'Sign-out failed.')
      }

      window.location.reload()
    } catch (error) {
      setAuthError(error.message || 'Sign-out failed. Please try again.')
    }
  }

  const totalProducts = new Set(
    inventory.map((medicine) => medicine.sku)
  ).size

  const lowStockCount = inventory.filter(
    (medicine) => getStockStatus(medicine) === 'Low stock'
  ).length

  const outOfStockCount = inventory.filter(
    (medicine) => getStockStatus(medicine) === 'Out of stock'
  ).length

  const expiredCount = inventory.filter(
    (medicine) =>
      medicine.quantity > 0 && getStockStatus(medicine) === 'Expired'
  ).length

  const today = new Date()
  today.setHours(0, 0, 0, 0)

  const expiringSoonCount = inventory.filter((medicine) => {
    const expiryDate = new Date(`${medicine.expiry}T00:00:00`)
    const daysUntilExpiry = Math.ceil(
      (expiryDate - today) / (1000 * 60 * 60 * 24)
    )

    return (
      medicine.quantity > 0 &&
      daysUntilExpiry >= 0 &&
      daysUntilExpiry <= 90
    )
  }).length

  const reorderSuggestions = [...new Set(inventory.map((item) => item.sku))]
    .map((sku) => {
      const batches = inventory.filter((item) => item.sku === sku)
      const product = batches[0]
      const totalQuantity = batches.reduce(
        (total, item) => total + item.quantity,
        0
      )
      const reorderLevel = product.reorderLevel

      return {
        sku,
        name: product.name,
        totalQuantity,
        reorderLevel,
        suggestedOrder: Math.max(0, reorderLevel * 2 - totalQuantity),
      }
    })
    .filter(
      (product) =>
        product.totalQuantity <= product.reorderLevel &&
        product.suggestedOrder > 0
    )

  const filteredMedicines = inventory.filter((medicine) => {
    const searchableText =
      `${medicine.name} ${medicine.category} ${medicine.sku} ${medicine.batch}`.toLowerCase()

    const matchesSearch = searchableText.includes(
      searchTerm.trim().toLowerCase()
    )
    const matchesStatus =
      statusFilter === 'all' || getStockStatus(medicine) === statusFilter

    return matchesSearch && matchesStatus
  })

  function handleFormChange(event) {
    const { name, value } = event.target
    setNewBatch((current) => ({ ...current, [name]: value }))
  }

  function handleDispenseFormChange(event) {
    const { name, value } = event.target
    setDispenseForm((current) => ({ ...current, [name]: value }))
  }

  function handleStockCountFormChange(event) {
    const { name, value } = event.target
    setStockCountForm((current) => ({ ...current, [name]: value }))
  }

  function handleAddBatch(event) {
    event.preventDefault()

    const batchNumber = newBatch.batch.trim()

    if (
      inventory.some(
        (item) => item.batch.toLowerCase() === batchNumber.toLowerCase()
      )
    ) {
      setFormError('That batch number is already in the inventory.')
      return
    }

    const quantity = Number(newBatch.quantity)
    const reorderLevel = Number(newBatch.reorderLevel)
    const purchaseCost = Number(newBatch.purchaseCost)
    const sellingPrice = Number(newBatch.sellingPrice)
    const sku = newBatch.sku.trim()
    const name = newBatch.name.trim()
    const supplier = newBatch.supplier.trim()
    const reference = newBatch.reference.trim()

    const receiptRecord = {
      id: `${batchNumber}-${Date.now()}`,
      type: 'Received',
      name,
      sku,
      batch: batchNumber,
      quantity,
      supplier,
      recipient: '',
      reference,
      recordedAt: new Date().toISOString(),
    }

    setInventory((current) => [
      ...current,
      {
        ...newBatch,
        sku,
        name,
        category: newBatch.category.trim(),
        batch: batchNumber,
        supplier,
        reference,
        quantity,
        reorderLevel,
        purchaseCost,
        sellingPrice,
      },
    ])

    setStockMovements((current) => [receiptRecord, ...current])
    setNewBatch(emptyBatch)
    setFormError('')
    setShowAddForm(false)
  }

  function handleDispense(event) {
    event.preventDefault()

    const quantity = Number(dispenseForm.quantity)
    const transactionType = dispenseForm.transactionType
    const amountReceived = Number(dispenseForm.amountReceived)
    const paymentMethod = dispenseForm.paymentMethod
    const recipient = dispenseForm.recipient.trim()
    const reference = dispenseForm.reference.trim()

    if (!recipient || !reference || !Number.isInteger(quantity) || quantity <= 0) {
      setDispenseError('Enter a valid quantity, recipient, and reference.')
      return
    }

    const dispenseDate = new Date()
    dispenseDate.setHours(0, 0, 0, 0)

    const eligibleBatches = inventory
      .filter(
        (item) =>
          item.sku === dispenseForm.sku &&
          item.quantity > 0 &&
          new Date(`${item.expiry}T00:00:00`) >= dispenseDate
      )
      .sort((first, second) => first.expiry.localeCompare(second.expiry))

    const availableQuantity = eligibleBatches.reduce(
      (total, item) => total + item.quantity,
      0
    )

    if (quantity > availableQuantity) {
      setDispenseError(
        `Only ${availableQuantity} units are available in non-expired batches.`
      )
      return
    }

    let remaining = quantity
    const allocations = []

    for (const item of eligibleBatches) {
      if (remaining === 0) break

      const quantityFromBatch = Math.min(item.quantity, remaining)
      allocations.push({ batch: item, quantity: quantityFromBatch })
      remaining -= quantityFromBatch
    }

    const saleAmount =
      transactionType === 'Sale'
        ? allocations.reduce(
            (total, allocation) =>
              total +
              allocation.quantity * Number(allocation.batch.sellingPrice || 0),
            0
          )
        : 0

    const costAmount =
      transactionType === 'Sale'
        ? allocations.reduce(
            (total, allocation) =>
              total +
              allocation.quantity * Number(allocation.batch.purchaseCost || 0),
            0
          )
        : 0

    if (
      transactionType === 'Sale' &&
      (!paymentMethod ||
        !Number.isFinite(amountReceived) ||
        amountReceived < 0 ||
        amountReceived > saleAmount)
    ) {
      setDispenseError(
        `Enter a payment method and an amount received from 0 to ${saleAmount}.`
      )
      return
    }

    setInventory((current) =>
      current.map((item) => {
        const allocation = allocations.find(
          (entry) => entry.batch.batch === item.batch
        )

        return allocation
          ? { ...item, quantity: item.quantity - allocation.quantity }
          : item
      })
    )

    const recordedAt = new Date().toISOString()
    const movements = allocations.map((allocation, index) => ({
      id: `${allocation.batch.batch}-${Date.now()}-${index}`,
      type: transactionType,
      name: allocation.batch.name,
      sku: allocation.batch.sku,
      batch: allocation.batch.batch,
      quantity: -allocation.quantity,
      supplier: '',
      recipient,
      reference,
      recordedAt,
    }))

    setStockMovements((current) => [...movements, ...current])
    if (transactionType === 'Sale') {
      setSales((current) => [
        {
          id: `SALE-${Date.now()}`,
          sku: dispenseForm.sku,
          name: allocations[0]?.batch.name || '',
          quantity,
          saleAmount,
          costAmount,
          grossProfit: saleAmount - costAmount,
          amountReceived,
          balanceDue: saleAmount - amountReceived,
          paymentMethod,
          recipient,
          reference,
          recordedAt,
        },
        ...current,
      ])
    }

    setDispenseForm(emptyDispense)
    setDispenseError('')
    setShowDispenseForm(false)
  }



  function handleSupplierInvoiceChange(event) {
    const { name, value } = event.target
    setSupplierInvoiceForm((current) => ({ ...current, [name]: value }))
  }

  function handleSupplierPaymentChange(event) {
    const { name, value } = event.target
    setSupplierPaymentForm((current) => ({ ...current, [name]: value }))
  }

  function handleSaveSupplierInvoice(event) {
    event.preventDefault()

    const supplier = supplierInvoiceForm.supplier.trim()
    const invoiceNumber = supplierInvoiceForm.invoiceNumber.trim()
    const invoiceAmount = Number(supplierInvoiceForm.invoiceAmount)
    const amountPaid = Number(supplierInvoiceForm.amountPaid)

    if (
      !supplier ||
      !invoiceNumber ||
      !supplierInvoiceForm.dueDate ||
      !Number.isFinite(invoiceAmount) ||
      invoiceAmount <= 0 ||
      !Number.isFinite(amountPaid) ||
      amountPaid < 0 ||
      amountPaid > invoiceAmount
    ) {
      setSupplierInvoiceError('Enter invoice details and valid amounts. Amount paid cannot exceed the invoice total.')
      return
    }

    if (supplierInvoices.some((invoice) => invoice.invoiceNumber.toLowerCase() === invoiceNumber.toLowerCase())) {
      setSupplierInvoiceError('That invoice number has already been entered.')
      return
    }

    const invoice = {
      id: `INV-${Date.now()}`,
      supplier,
      invoiceNumber,
      invoiceAmount,
      amountPaid,
      dueDate: supplierInvoiceForm.dueDate,
      createdAt: new Date().toISOString(),
    }

    setSupplierInvoices((current) => [invoice, ...current])

    if (amountPaid > 0) {
      setSupplierPayments((current) => [{
        id: `PAY-${Date.now()}`,
        invoiceId: invoice.id,
        supplier,
        invoiceNumber,
        amount: amountPaid,
        method: 'Opening payment',
        reference: invoiceNumber,
        recordedAt: invoice.createdAt,
      }, ...current])
    }

    setSupplierInvoiceForm(emptySupplierInvoice)
    setSupplierInvoiceError('')
    setShowSupplierInvoiceForm(false)
  }

  function handleRecordSupplierPayment(event) {
    event.preventDefault()

    const amount = Number(supplierPaymentForm.amount)
    const reference = supplierPaymentForm.reference.trim()
    const invoice = supplierInvoices.find((item) => item.id === supplierPaymentForm.invoiceId)

    if (!invoice || !supplierPaymentForm.method || !reference || !Number.isFinite(amount) || amount <= 0) {
      setSupplierPaymentError('Select an invoice and enter a valid payment, method, and reference.')
      return
    }

    const balance = invoice.invoiceAmount - invoice.amountPaid
    if (amount > balance) {
      setSupplierPaymentError(`Payment cannot exceed the remaining balance of ${balance.toLocaleString()}.`)
      return
    }

    const recordedAt = new Date().toISOString()
    setSupplierInvoices((current) => current.map((item) =>
      item.id === invoice.id ? { ...item, amountPaid: item.amountPaid + amount } : item
    ))
    setSupplierPayments((current) => [{
      id: `PAY-${Date.now()}`,
      invoiceId: invoice.id,
      supplier: invoice.supplier,
      invoiceNumber: invoice.invoiceNumber,
      amount,
      method: supplierPaymentForm.method,
      reference,
      recordedAt,
    }, ...current])

    setSupplierPaymentForm(emptySupplierPayment)
    setSupplierPaymentError('')
    setShowSupplierPaymentForm(false)
  }

  function handleCustomerPaymentChange(event) {
    const { name, value } = event.target
    setCustomerPaymentForm((current) => ({ ...current, [name]: value }))
  }

  function handleRecordCustomerPayment(event) {
    event.preventDefault()

    const sale = sales.find((item) => item.id === customerPaymentForm.saleId)
    const amount = Number(customerPaymentForm.amount)
    const method = customerPaymentForm.method
    const reference = customerPaymentForm.reference.trim()

    if (!sale || !method || !reference || !Number.isFinite(amount) || amount <= 0) {
      setCustomerPaymentError('Select an outstanding sale and enter a valid payment, method, and reference.')
      return
    }

    if (amount > sale.balanceDue) {
      setCustomerPaymentError(`Payment cannot exceed the outstanding balance of ${sale.balanceDue.toLocaleString()}.`)
      return
    }

    const recordedAt = new Date().toISOString()
    const newAmountReceived = Number((sale.amountReceived + amount).toFixed(2))
    const newBalanceDue = Number((sale.balanceDue - amount).toFixed(2))

    setSales((current) => current.map((item) =>
      item.id === sale.id
        ? { ...item, amountReceived: newAmountReceived, balanceDue: newBalanceDue }
        : item
    ))

    setCustomerPayments((current) => [{
      id: `CUST-PAY-${Date.now()}`,
      saleId: sale.id,
      saleReference: sale.reference,
      customer: sale.recipient,
      amount,
      method,
      reference,
      recordedAt,
    }, ...current])

    setCustomerPaymentForm(emptyCustomerPayment)
    setCustomerPaymentError('')
    setShowCustomerPaymentForm(false)
  }

  function handleStockCount(event) {
    event.preventDefault()

    const countedQuantity = Number(stockCountForm.quantity)
    const reference = stockCountForm.reference.trim()
    const reason = stockCountForm.reason

    if (
      !stockCountForm.batch ||
      !Number.isInteger(countedQuantity) ||
      countedQuantity < 0 ||
      !reason ||
      !reference
    ) {
      setStockCountError(
        'Select a batch, enter a whole-number count of zero or more, and provide a reason and reference.'
      )
      return
    }

    const countedBatch = inventory.find(
      (item) => item.batch === stockCountForm.batch
    )

    if (!countedBatch) {
      setStockCountError('The selected batch could not be found.')
      return
    }

    const difference = countedQuantity - countedBatch.quantity

    if (difference === 0) {
      setStockCountError(
        'The counted quantity matches the recorded quantity. No adjustment is needed.'
      )
      return
    }

    setInventory((current) =>
      current.map((item) =>
        item.batch === countedBatch.batch
          ? { ...item, quantity: countedQuantity }
          : item
      )
    )

    setStockMovements((current) => [
      {
        id: `${countedBatch.batch}-count-${Date.now()}`,
        type: 'Stock count adjustment',
        name: countedBatch.name,
        sku: countedBatch.sku,
        batch: countedBatch.batch,
        quantity: difference,
        supplier: '',
        recipient: reason,
        reference,
        recordedAt: new Date().toISOString(),
      },
      ...current,
    ])

    setStockCountForm(emptyStockCount)
    setStockCountError('')
    setShowStockCountForm(false)
  }

  const navPages = ['Overview', 'Inventory', 'Suppliers', 'Reports']

  if (authLoading) {
    return <main className="auth-page">Checking your sign-in…</main>
  }

  if (!currentUser) {
    return (
      <LoginScreen
        username={loginUsername}
        setUsername={setLoginUsername}
        password={loginPassword}
        setPassword={setLoginPassword}
        error={authError}
        isSubmitting={loginSubmitting}
        onSubmit={handleLogin}
      />
    )
  }

  return (
    <div className={`app-layout${isSidebarCollapsed ? ' sidebar-collapsed' : ''}`}>
      <aside className="sidebar">
        <h2 className="sidebar-brand">Wellnest</h2>

        <button
          className="sidebar-toggle"
          type="button"
          onClick={() => setIsSidebarCollapsed((collapsed) => !collapsed)}
          aria-label={isSidebarCollapsed ? 'Show navigation' : 'Hide navigation'}
          aria-expanded={!isSidebarCollapsed}
          aria-controls="primary-navigation"
          title={isSidebarCollapsed ? 'Show navigation' : 'Hide navigation'}
        >
          <span aria-hidden="true">{isSidebarCollapsed ? '›' : '‹'}</span>
        </button>

        <nav id="primary-navigation" aria-label="Main navigation">
          {navPages.map((page) => (
            <button
              key={page}
              type="button"
              className={activePage === page ? 'nav-link active' : 'nav-link'}
              onClick={() => setActivePage(page)}
              aria-current={activePage === page ? 'page' : undefined}
              title={page}
            >
              <span className="nav-icon" aria-hidden="true">{page[0]}</span>
              <span className="nav-label">{page}</span>
            </button>
          ))}
        </nav>
      </aside>

      <main className="main-content">
        <header className="topbar">
          <h1>
            {activePage === 'Overview' ? 'Pharmacy Inventory' : activePage}
          </h1>
          <div className="topbar-actions">
            <span>
              Signed in as {currentUser.firstName || currentUser.username}
            </span>
            <button type="button" onClick={handleLogout}>
              Sign out
            </button>
            {authError && <span className="auth-error" role="alert">{authError}</span>}
          </div>
        </header>

        <section className="dashboard">
          {activePage === 'Overview' && (
            <>
              <h2>Good morning</h2>
              <p>Here’s an overview of your pharmacy stock.</p>

              <div className="summary-cards">
                <article className="summary-card">
                  <span>Total products</span>
                  <strong>{totalProducts}</strong>
                </article>

                <article className="summary-card">
                  <span>Low stock items</span>
                  <strong>{lowStockCount}</strong>
                </article>

                <article className="summary-card">
                  <span>Out of stock</span>
                  <strong>{outOfStockCount}</strong>
                </article>

                <article className="summary-card">
                  <span>Expiring within 90 days</span>
                  <strong>{expiringSoonCount}</strong>
                </article>

                <article className="summary-card">
                  <span>Expired stock</span>
                  <strong>{expiredCount}</strong>
                </article>
              </div>

              <section className="inventory-panel">
                <div className="inventory-heading">
                  <div>
                    <h2>Reorder suggestions</h2>
                    <p>Products at or below their reorder level.</p>
                  </div>
                </div>

                <table>
                  <thead>
                    <tr>
                      <th>SKU</th>
                      <th>Medicine</th>
                      <th>Current stock</th>
                      <th>Reorder level</th>
                      <th>Suggested order</th>
                    </tr>
                  </thead>

                  <tbody>
                    {reorderSuggestions.map((product) => (
                      <tr key={product.sku}>
                        <td>{product.sku}</td>
                        <td>{product.name}</td>
                        <td>{product.totalQuantity}</td>
                        <td>{product.reorderLevel}</td>
                        <td>{product.suggestedOrder}</td>
                      </tr>
                    ))}

                    {reorderSuggestions.length === 0 && (
                      <tr>
                        <td colSpan="5">
                          No products currently need reordering.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </section>
            </>
          )}

          {activePage === 'Inventory' && (
            <section className="inventory-panel">
              <div className="inventory-heading">
                <div>
                  <h2>Medicine inventory</h2>
                  <p>Check current stock levels.</p>
                </div>

                <input
                  className="inventory-search"
                  type="search"
                  placeholder="Search medicines..."
                  aria-label="Search medicines"
                  value={searchTerm}
                  onChange={(event) => setSearchTerm(event.target.value)}
                />

                <select
                  className="inventory-filter"
                  value={statusFilter}
                  onChange={(event) => setStatusFilter(event.target.value)}
                  aria-label="Filter by stock status"
                >
                  <option value="all">All statuses</option>
                  <option value="In stock">In stock</option>
                  <option value="Low stock">Low stock</option>
                  <option value="Out of stock">Out of stock</option>
                  <option value="Expired">Expired</option>
                </select>

                <button
                  type="button"
                  onClick={() => setShowAddForm((shown) => !shown)}
                >
                  {showAddForm ? 'Close add form' : 'Add batch'}
                </button>

                <button
                  type="button"
                  onClick={() => setShowDispenseForm((shown) => !shown)}
                >
                  {showDispenseForm ? 'Close dispense form' : 'Dispense stock'}
                </button>

                <button
                  type="button"
                  onClick={() => setShowStockCountForm((shown) => !shown)}
                >
                  {showStockCountForm ? 'Close stock count' : 'Stock count'}
                </button>
              </div>

              {showAddForm && (
                <form className="batch-form" onSubmit={handleAddBatch}>
                  <label>
                    SKU
                    <input
                      name="sku"
                      value={newBatch.sku}
                      onChange={handleFormChange}
                      required
                    />
                  </label>

                  <label>
                    Medicine
                    <input
                      name="name"
                      value={newBatch.name}
                      onChange={handleFormChange}
                      required
                    />
                  </label>

                  <label>
                    Category
                    <input
                      name="category"
                      value={newBatch.category}
                      onChange={handleFormChange}
                      required
                    />
                  </label>

                  <label>
                    Batch number
                    <input
                      name="batch"
                      value={newBatch.batch}
                      onChange={handleFormChange}
                      required
                    />
                  </label>

                  <label>
                    Quantity
                    <input
                      name="quantity"
                      type="number"
                      min="0"
                      step="1"
                      value={newBatch.quantity}
                      onChange={handleFormChange}
                      required
                    />
                  </label>

                  <label>
                    Reorder level
                    <input
                      name="reorderLevel"
                      type="number"
                      min="0"
                      step="1"
                      value={newBatch.reorderLevel}
                      onChange={handleFormChange}
                      required
                    />
                  </label>

                  <label>
                    Purchase cost per unit
                    <input
                      name="purchaseCost"
                      type="number"
                      min="0"
                      step="0.01"
                      value={newBatch.purchaseCost}
                      onChange={handleFormChange}
                      required
                    />
                  </label>

                  <label>
                    Selling price per unit
                    <input
                      name="sellingPrice"
                      type="number"
                      min="0"
                      step="0.01"
                      value={newBatch.sellingPrice}
                      onChange={handleFormChange}
                      required
                    />
                  </label>

                  <label>
                    Expiry date
                    <input
                      name="expiry"
                      type="date"
                      value={newBatch.expiry}
                      onChange={handleFormChange}
                      required
                    />
                  </label>

                  <label>
                    Supplier / source
                    <input
                      name="supplier"
                      value={newBatch.supplier}
                      onChange={handleFormChange}
                      required
                    />
                  </label>

                  <label>
                    Receipt / invoice reference
                    <input
                      name="reference"
                      value={newBatch.reference}
                      onChange={handleFormChange}
                      required
                    />
                  </label>

                  {formError && <p className="form-error">{formError}</p>}

                  <button type="submit">Save batch</button>
                </form>
              )}

              {showDispenseForm && (
                <form className="batch-form" onSubmit={handleDispense}>
                  <label>
                    Medicine
                    <select
                      name="sku"
                      value={dispenseForm.sku}
                      onChange={handleDispenseFormChange}
                      required
                    >
                      <option value="">Select medicine</option>
                      {[
                        ...new Map(
                          inventory.map((item) => [item.sku, item])
                        ).values(),
                      ].map((medicine) => (
                        <option key={medicine.sku} value={medicine.sku}>
                          {medicine.name}
                        </option>
                      ))}
                    </select>
                  </label>

                  <label>
                    Transaction type
                    <select
                      name="transactionType"
                      value={dispenseForm.transactionType}
                      onChange={handleDispenseFormChange}
                      required
                    >
                      <option value="Sale">Sale</option>
                      <option value="Non-sale issue">Non-sale issue</option>
                    </select>
                  </label>

                  <label>
                    Quantity to dispense
                    <input
                      name="quantity"
                      type="number"
                      min="1"
                      step="1"
                      value={dispenseForm.quantity}
                      onChange={handleDispenseFormChange}
                      required
                    />
                  </label>

                  <label>
                    Supplied to
                    <input
                      name="recipient"
                      value={dispenseForm.recipient}
                      onChange={handleDispenseFormChange}
                      required
                    />
                  </label>

                  <label>
                    Sale / issue reference
                    <input
                      name="reference"
                      value={dispenseForm.reference}
                      onChange={handleDispenseFormChange}
                      required
                    />
                  </label>


                  {dispenseForm.transactionType === 'Sale' && (
                    <>
                      <label>
                        Amount received
                        <input
                          name="amountReceived"
                          type="number"
                          min="0"
                          step="0.01"
                          value={dispenseForm.amountReceived}
                          onChange={handleDispenseFormChange}
                          required
                        />
                      </label>

                      <label>
                        Payment method
                        <select
                          name="paymentMethod"
                          value={dispenseForm.paymentMethod}
                          onChange={handleDispenseFormChange}
                          required
                        >
                          <option value="">Select payment method</option>
                          <option value="Cash">Cash</option>
                          <option value="Mobile money">Mobile money</option>
                          <option value="Bank transfer">Bank transfer</option>
                          <option value="Card">Card</option>
                          <option value="Credit">Credit</option>
                        </select>
                      </label>
                    </>
                  )}
                  {dispenseError && (
                    <p className="form-error">{dispenseError}</p>
                  )}

                  <button type="submit">Record dispensing</button>
                </form>
              )}

              {showStockCountForm && (
                <form className="batch-form" onSubmit={handleStockCount}>
                  <label>
                    Batch to count
                    <select
                      name="batch"
                      value={stockCountForm.batch}
                      onChange={handleStockCountFormChange}
                      required
                    >
                      <option value="">Select a batch</option>
                      {inventory.map((medicine) => (
                        <option key={medicine.batch} value={medicine.batch}>
                          {medicine.name} — {medicine.batch} (recorded:{' '}
                          {medicine.quantity})
                        </option>
                      ))}
                    </select>
                  </label>

                  <label>
                    Quantity counted on shelf
                    <input
                      name="quantity"
                      type="number"
                      min="0"
                      step="1"
                      value={stockCountForm.quantity}
                      onChange={handleStockCountFormChange}
                      required
                    />
                  </label>

                  <label>
                    Reason for difference
                    <select
                      name="reason"
                      value={stockCountForm.reason}
                      onChange={handleStockCountFormChange}
                      required
                    >
                      <option value="">Select a reason</option>
                      <option value="Damaged stock">Damaged stock</option>
                      <option value="Expired stock">Expired stock</option>
                      <option value="Loss or theft">Loss or theft</option>
                      <option value="Counting correction">
                        Counting correction
                      </option>
                      <option value="Other">Other</option>
                    </select>
                  </label>

                  <label>
                    Count / adjustment reference
                    <input
                      name="reference"
                      value={stockCountForm.reference}
                      onChange={handleStockCountFormChange}
                      placeholder="For example: COUNT-2026-001"
                      required
                    />
                  </label>

                  {stockCountError && (
                    <p className="form-error">{stockCountError}</p>
                  )}

                  <button type="submit">Save stock count</button>
                </form>
              )}

              <table>
                <thead>
                  <tr>
                    <th>SKU</th>
                    <th>Medicine</th>
                    <th>Batch</th>
                    <th>Category</th>
                    <th>Quantity</th>
                    <th>Purchase cost / unit</th>
                    <th>Selling price / unit</th>
                    <th>Gross profit / unit</th>
                    <th>Expiry date</th>
                    <th>Status</th>
                  </tr>
                </thead>

                <tbody>
                  {filteredMedicines.map((medicine) => {
                    const status = getStockStatus(medicine)
                    const statusClass = {
                      'In stock': 'in-stock',
                      'Low stock': 'low-stock',
                      'Out of stock': 'out-of-stock',
                      Expired: 'expired',
                    }[status]

                    return (
                      <tr key={medicine.batch}>
                        <td>{medicine.sku}</td>
                        <td>{medicine.name}</td>
                        <td>{medicine.batch}</td>
                        <td>{medicine.category}</td>
                        <td>{medicine.quantity}</td>
                        <td>{Number(medicine.purchaseCost || 0).toLocaleString()}</td>
                        <td>{Number(medicine.sellingPrice || 0).toLocaleString()}</td>
                        <td>{(Number(medicine.sellingPrice || 0) - Number(medicine.purchaseCost || 0)).toLocaleString()}</td>
                        <td>{medicine.expiry}</td>
                        <td>
                          <span className={`stock-status ${statusClass}`}>
                            {status}
                          </span>
                        </td>
                      </tr>
                    )
                  })}

                  {filteredMedicines.length === 0 && (
                    <tr>
                      <td colSpan="10">No matching batches found.</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </section>
          )}
          {activePage === 'Suppliers' && (
            <>
              <section className="inventory-panel">
                <div className="inventory-heading">
                  <div>
                    <h2>Supplier invoices</h2>
                    <p>Track invoice totals, due dates, payments, and balances.</p>
                  </div>
                  <button type="button" onClick={() => setShowSupplierInvoiceForm((shown) => !shown)}>
                    {showSupplierInvoiceForm ? 'Close invoice form' : 'Add supplier invoice'}
                  </button>
                  <button type="button" onClick={() => setShowSupplierPaymentForm((shown) => !shown)}>
                    {showSupplierPaymentForm ? 'Close payment form' : 'Record payment'}
                  </button>
                </div>

                {showSupplierInvoiceForm && (
                  <form className="batch-form" onSubmit={handleSaveSupplierInvoice}>
                    <label>Supplier<input name="supplier" value={supplierInvoiceForm.supplier} onChange={handleSupplierInvoiceChange} required /></label>
                    <label>Invoice number<input name="invoiceNumber" value={supplierInvoiceForm.invoiceNumber} onChange={handleSupplierInvoiceChange} required /></label>
                    <label>Invoice total<input name="invoiceAmount" type="number" min="0.01" step="0.01" value={supplierInvoiceForm.invoiceAmount} onChange={handleSupplierInvoiceChange} required /></label>
                    <label>Amount already paid<input name="amountPaid" type="number" min="0" step="0.01" value={supplierInvoiceForm.amountPaid} onChange={handleSupplierInvoiceChange} required /></label>
                    <label>Due date<input name="dueDate" type="date" value={supplierInvoiceForm.dueDate} onChange={handleSupplierInvoiceChange} required /></label>
                    {supplierInvoiceError && <p className="form-error">{supplierInvoiceError}</p>}
                    <button type="submit">Save invoice</button>
                  </form>
                )}

                {showSupplierPaymentForm && (
                  <form className="batch-form" onSubmit={handleRecordSupplierPayment}>
                    <label>Invoice<select name="invoiceId" value={supplierPaymentForm.invoiceId} onChange={handleSupplierPaymentChange} required>
                      <option value="">Select an unpaid invoice</option>
                      {supplierInvoices.filter((invoice) => invoice.invoiceAmount > invoice.amountPaid).map((invoice) => (
                        <option key={invoice.id} value={invoice.id}>{invoice.supplier} — {invoice.invoiceNumber} — balance {((invoice.invoiceAmount - invoice.amountPaid).toLocaleString())}</option>
                      ))}
                    </select></label>
                    <label>Payment amount<input name="amount" type="number" min="0.01" step="0.01" value={supplierPaymentForm.amount} onChange={handleSupplierPaymentChange} required /></label>
                    <label>Payment method<select name="method" value={supplierPaymentForm.method} onChange={handleSupplierPaymentChange} required>
                      <option value="">Select method</option><option value="Cash">Cash</option><option value="Mobile money">Mobile money</option><option value="Bank transfer">Bank transfer</option><option value="Card">Card</option>
                    </select></label>
                    <label>Payment reference<input name="reference" value={supplierPaymentForm.reference} onChange={handleSupplierPaymentChange} required /></label>
                    {supplierPaymentError && <p className="form-error">{supplierPaymentError}</p>}
                    <button type="submit">Save payment</button>
                  </form>
                )}

                <table>
                  <thead><tr><th>Supplier</th><th>Invoice</th><th>Invoice total</th><th>Paid</th><th>Balance</th><th>Due date</th><th>Status</th></tr></thead>
                  <tbody>
                    {supplierInvoices.map((invoice) => {
                      const balance = invoice.invoiceAmount - invoice.amountPaid
                      const status = getSupplierInvoiceStatus(invoice)
                      return <tr key={invoice.id}>
                        <td>{invoice.supplier}</td><td>{invoice.invoiceNumber}</td>
                        <td>{invoice.invoiceAmount.toLocaleString()}</td><td>{invoice.amountPaid.toLocaleString()}</td>
                        <td>{balance.toLocaleString()}</td><td>{invoice.dueDate}</td><td>{status}</td>
                      </tr>
                    })}
                    {supplierInvoices.length === 0 && <tr><td colSpan="7">No supplier invoices recorded yet.</td></tr>}
                  </tbody>
                </table>
              </section>

              <section className="inventory-panel">
                <div className="inventory-heading"><div><h2>Supplier payment history</h2><p>Payments entered against supplier invoices.</p></div></div>
                <table>
                  <thead><tr><th>Date</th><th>Supplier</th><th>Invoice</th><th>Amount</th><th>Method</th><th>Reference</th></tr></thead>
                  <tbody>
                    {supplierPayments.map((payment) => <tr key={payment.id}>
                      <td>{new Date(payment.recordedAt).toLocaleString()}</td><td>{payment.supplier}</td><td>{payment.invoiceNumber}</td><td>{payment.amount.toLocaleString()}</td><td>{payment.method}</td><td>{payment.reference}</td>
                    </tr>)}
                    {supplierPayments.length === 0 && <tr><td colSpan="6">No supplier payments recorded yet.</td></tr>}
                  </tbody>
                </table>
              </section>

              <section className="inventory-panel">
                <div className="inventory-heading"><div><h2>Received stock by supplier</h2><p>Receipt records created when batches were added.</p></div></div>
                <table>
                  <thead><tr><th>Supplier</th><th>Medicine</th><th>Batch</th><th>Quantity received</th><th>Reference</th></tr></thead>
                  <tbody>
                    {stockMovements.filter((movement) => movement.type === 'Received').map((movement) => <tr key={movement.id}>
                      <td>{movement.supplier}</td><td>{movement.name}</td><td>{movement.batch}</td><td>{movement.quantity}</td><td>{movement.reference}</td>
                    </tr>)}
                    {!stockMovements.some((movement) => movement.type === 'Received') && <tr><td colSpan="5">No supplier receipts recorded yet.</td></tr>}
                  </tbody>
                </table>
              </section>
            </>
          )}

          {activePage === 'Reports' && (
            <>
              <section className="inventory-panel movement-panel">
              <div className="inventory-heading">
                <div>
                  <h2>Recent stock activity</h2>
                  <p>Track received, dispensed, and stock-count adjustments.</p>
                </div>
              </div>

              <table>
                <thead>
                  <tr>
                    <th>Date and time</th>
                    <th>Activity</th>
                    <th>Medicine</th>
                    <th>Batch</th>
                    <th>Quantity change</th>
                    <th>Supplier / recipient / reason</th>
                    <th>Reference</th>
                  </tr>
                </thead>

                <tbody>
                  {stockMovements.map((movement) => (
                    <tr key={movement.id}>
                      <td>{new Date(movement.recordedAt).toLocaleString()}</td>
                      <td>{movement.type}</td>
                      <td>{movement.name}</td>
                      <td>{movement.batch}</td>
                      <td>
                        {movement.quantity > 0 ? '+' : ''}
                        {movement.quantity}
                      </td>
                      <td>
                        {movement.recipient || movement.supplier || '—'}
                      </td>
                      <td>{movement.reference}</td>
                    </tr>
                  ))}

                  {stockMovements.length === 0 && (
                    <tr>
                      <td colSpan="7">No stock activity recorded yet.</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </section>

              <section className="inventory-panel">
                <div className="inventory-heading">
                  <div>
                    <h2>Sales and payments</h2>
                    <p>Recorded sales, amounts received, and outstanding balances.</p>
                  </div>
                  <button type="button" onClick={() => setShowCustomerPaymentForm((shown) => !shown)}>
                    {showCustomerPaymentForm ? 'Close payment form' : 'Record customer payment'}
                  </button>
                </div>

                {showCustomerPaymentForm && (
                  <form className="batch-form" onSubmit={handleRecordCustomerPayment}>
                    <label>Outstanding sale
                      <select name="saleId" value={customerPaymentForm.saleId} onChange={handleCustomerPaymentChange} required>
                        <option value="">Select a sale with a balance</option>
                        {sales.filter((sale) => sale.balanceDue > 0).map((sale) => (
                          <option key={sale.id} value={sale.id}>
                            {sale.recipient} — {sale.name} — {sale.reference} — due {sale.balanceDue.toLocaleString()}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label>Payment amount
                      <input name="amount" type="number" min="0.01" step="0.01" value={customerPaymentForm.amount} onChange={handleCustomerPaymentChange} required />
                    </label>
                    <label>Payment method
                      <select name="method" value={customerPaymentForm.method} onChange={handleCustomerPaymentChange} required>
                        <option value="">Select method</option>
                        <option value="Cash">Cash</option>
                        <option value="Mobile money">Mobile money</option>
                        <option value="Bank transfer">Bank transfer</option>
                        <option value="Card">Card</option>
                      </select>
                    </label>
                    <label>Payment reference
                      <input name="reference" value={customerPaymentForm.reference} onChange={handleCustomerPaymentChange} required />
                    </label>
                    {customerPaymentError && <p className="form-error">{customerPaymentError}</p>}
                    <button type="submit">Save customer payment</button>
                  </form>
                )}

                <table>
                  <thead>
                    <tr>
                      <th>Date</th>
                      <th>Medicine</th>
                      <th>Quantity</th>
                      <th>Sale total</th>
                      <th>Gross profit</th>
                      <th>Received</th>
                      <th>Balance due</th>
                      <th>Payment status</th>
                      <th>Original payment method</th>
                      <th>Reference</th>
                    </tr>
                  </thead>
                  <tbody>
                    {sales.map((sale) => (
                      <tr key={sale.id}>
                        <td>{new Date(sale.recordedAt).toLocaleString()}</td>
                        <td>{sale.name}</td>
                        <td>{sale.quantity}</td>
                        <td>{sale.saleAmount.toLocaleString()}</td>
                        <td>{sale.grossProfit.toLocaleString()}</td>
                        <td>{sale.amountReceived.toLocaleString()}</td>
                        <td>{sale.balanceDue.toLocaleString()}</td>
                        <td>{getSalePaymentStatus(sale)}</td>
                        <td>{sale.paymentMethod}</td>
                        <td>{sale.reference}</td>
                      </tr>
                    ))}
                    {sales.length === 0 && (
                      <tr>
                        <td colSpan="10">No sales recorded yet.</td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </section>
              <section className="inventory-panel">
                <div className="inventory-heading">
                  <div>
                    <h2>Customer payment history</h2>
                    <p>Later payments recorded against sales.</p>
                  </div>
                </div>
                <table>
                  <thead>
                    <tr>
                      <th>Date</th>
                      <th>Customer</th>
                      <th>Sale reference</th>
                      <th>Amount</th>
                      <th>Method</th>
                      <th>Payment reference</th>
                    </tr>
                  </thead>
                  <tbody>
                    {customerPayments.map((payment) => (
                      <tr key={payment.id}>
                        <td>{new Date(payment.recordedAt).toLocaleString()}</td>
                        <td>{payment.customer}</td>
                        <td>{payment.saleReference}</td>
                        <td>{payment.amount.toLocaleString()}</td>
                        <td>{payment.method}</td>
                        <td>{payment.reference}</td>
                      </tr>
                    ))}
                    {customerPayments.length === 0 && (
                      <tr><td colSpan="6">No later customer payments recorded yet.</td></tr>
                    )}
                  </tbody>
                </table>
              </section>

            </>
          )}
        </section>
      </main>
    </div>
  )
}

export default App


