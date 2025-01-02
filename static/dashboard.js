// Payment handling
async function loadPaymentMethods() {
    try {
        const response = await fetch(`/payment-methods/1`);
        if (!response.ok) {
            throw new Error('Failed to load payment methods');
        }
        
        const data = await response.json();
        const paymentMethodsList = document.getElementById('payment-methods-list');
        if (!paymentMethodsList) {
            console.warn('Payment methods list element not found');
            return;
        }
        
        paymentMethodsList.innerHTML = '';
        
        // Handle empty data
        if (!Array.isArray(data) || data.length === 0) {
            paymentMethodsList.innerHTML = '<div class="py-2">No payment methods found</div>';
            return;
        }

        data.forEach(method => {
            if (method && method.card) {
                const div = document.createElement('div');
                div.className = 'flex justify-between items-center py-2';
                div.innerHTML = `
                    <span>${method.card.brand} ending in ${method.card.last4}</span>
                    <button onclick="setDefaultPaymentMethod('${method.id}')" 
                            class="bg-blue-500 text-white px-4 py-2 rounded hover:bg-blue-600">
                        Set Default
                    </button>
                `;
                paymentMethodsList.appendChild(div);
            }
        });
    } catch (error) {
        console.error('Error loading payment methods:', error);
        const paymentMethodsList = document.getElementById('payment-methods-list');
        if (paymentMethodsList) {
            paymentMethodsList.innerHTML = '<div class="py-2 text-red-500">Error loading payment methods</div>';
        }
    }
}

function showAddPaymentMethod() {
    document.getElementById('payment-modal').classList.remove('hidden');
    if (!elements) {
        elements = stripe.elements();
        const card = elements.create('card');
        card.mount('#card-element');
    }
}

function hidePaymentModal() {
    document.getElementById('payment-modal').classList.add('hidden');
}

async function setDefaultPaymentMethod(paymentMethodId) {
    try {
        const response = await fetch(`/setup-automatic-payments/1`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ payment_method_id: paymentMethodId }),
        });
        
        if (response.ok) {
            alert('Default payment method updated successfully');
            loadPaymentMethods();
        } else {
            throw new Error('Failed to update default payment method');
        }
    } catch (error) {
        console.error('Error setting default payment method:', error);
        alert('Error setting default payment method');
    }
}

// API Key management
async function createNewKey() {
    try {
        const name = prompt('Enter a name for the new API key:');
        if (!name) return;

        const response = await fetch('/api-keys', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                customer_id: 1,
                name: name
            }),
        });

        if (response.ok) {
            location.reload();
        } else {
            throw new Error('Failed to create API key');
        }
    } catch (error) {
        console.error('Error creating API key:', error);
        alert('Error creating API key');
    }
}

async function toggleKey(keyId) {
    try {
        const response = await fetch(`/api-keys/${keyId}/toggle`, {
            method: 'POST',
        });

        if (response.ok) {
            location.reload();
        } else {
            throw new Error('Failed to toggle API key');
        }
    } catch (error) {
        console.error('Error toggling API key:', error);
        alert('Error toggling API key');
    }
}

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    loadPaymentMethods();
    
    // Handle payment form submission
    const form = document.getElementById('payment-form');
    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        const button = form.querySelector('button');
        button.disabled = true;
        
        try {
            const { setupIntent, error } = await stripe.confirmCardSetup(
                clientSecret,
                {
                    payment_method: {
                        card: elements.getElement('card'),
                        billing_details: {
                            name: document.getElementById('cardholder-name').value,
                        },
                    },
                }
            );

            if (error) {
                throw new Error(error.message);
            }

            const response = await fetch(`/attach-payment-method/1`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    payment_method_id: setupIntent.payment_method,
                }),
            });

            if (!response.ok) {
                throw new Error('Failed to attach payment method');
            }

            alert('Payment method added successfully');
            hidePaymentModal();
            loadPaymentMethods();
        } catch (error) {
            console.error('Error:', error);
            alert(error.message);
        } finally {
            button.disabled = false;
        }
    });
});
