from flask import Flask, render_template, request, redirect, url_for, flash
from flask_bootstrap import Bootstrap
from flask_wtf import FlaskForm
from wtforms import StringField, FloatField, FileField, SelectField, PasswordField
from wtforms.validators import DataRequired
from werkzeug.utils import secure_filename
import os
from google.cloud import storage
import firebase_admin
from firebase_admin import credentials, firestore
import ast
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin, LoginManager, login_user, current_user

BUCKET_NAME = os.environ['STORE_BUCKET_NAME']
SERVICE_ACCOUNT_PATH = os.environ['GOOGLE_APPLICATION_CREDENTIALS']

# initialize Flask application
app = Flask(__name__)
app.secret_key = os.environ['SECRET_KEY']
# configure transitional layer for uploading images
app.config['UPLOAD_FOLDER'] = "uploaded_images"

# allow using Bootstrap templates
Bootstrap(app)

# create a login manager to work with authentication
login_manager = LoginManager()
# configure it for login
login_manager.init_app(app)

# instantiate a client
storage_client = storage.Client()

# uses a service account to initialize my own server
cred = credentials.Certificate(SERVICE_ACCOUNT_PATH)
firebase_admin.initialize_app(cred)
# initialize cloud firestore
db = firestore.client()

# initialize a cart as an empty list to store products in
cart = []


def upload_to_bucket(bucket_name, source_file_name, destination_blob_name):
    """ Uploads a file to the bucket. """
    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(destination_blob_name)
    blob.upload_from_filename(source_file_name)


def upload_to_firestore(name, category, price, weight, image_ref, description, keywords):
    """ Uploads a new product document to the firestore database. """
    document_ref = db.collection('products').document(f'{name.replace(" ", "_").lower()}')
    document_ref.set({
        'name': name,
        'category': category,
        'price': price,
        'weight': weight,
        'image': image_ref,
        'description': description,
        'keywords': keywords.lower()
    })


def get_all_products():
    """
    Retrieves all products from the firestore database,
    converts them into dictionaries and returns a list.
    :return: a list of all products as dictionaries
    """
    products_ref = db.collection('products')
    products = products_ref.stream()
    products_list = [doc.to_dict() for doc in products]
    return products_list


class User(UserMixin):
    """
    Create a custom User class that extend UserMixin and represents users.
    Used to implement some properties and methods for authentication.
    """

    def __init__(self, user_doc):
        """ Accepts firestore document as a parameter """
        self.user_doc = user_doc

    def get_id(self):
        """ Overrides the method to get a username as an id """
        user_id = self.user_doc['username']
        return str(user_id)


def get_authorized_users():
    """
    Retrieves all authorized users from the database,
    converts them into dictionaries and returns a list.
    :return: a list of authorized users
    """
    managers_ref = db.collection('store_managers')
    managers = managers_ref.stream()
    managers_list = [manager.to_dict() for manager in managers]
    return managers_list


def add_authorized_user():
    """
    Creates and adds a new user to the database.
    The password entered is hashed.
    Method was created and used for convenience purposes.
    """
    new_manager = {
        "username": input("Username: "),
        "password": input("Password: ")
    }

    new_manager["password"] = generate_password_hash(
        new_manager["password"],
        method='pbkdf2:sha256',
        salt_length=8
    )
    db.collection('store_managers').add(new_manager)

# left for testing purposes:
# add_authorized_user()


def searched_products(keywords):
    """
    Search function: compares entered words with every product keywords field.
    :param keywords: words entered in the search bar
    :return: a list of products to display
    """
    all_products = get_all_products()
    display_products = []
    for product in all_products:
        for word in keywords:
            if word.lower()[:5] in product['keywords']:
                display_products.append(product)
                break
    return display_products


def add_to_cart():
    """ Adds product to the cart """
    product_to_add = request.args.get('product')
    cart.append(product_to_add)


class LoginForm(FlaskForm):
    """ Defines a login form, which is a subclass of FlaskForm"""
    username = StringField('Username')
    password = PasswordField('Password')


class ProductForm(FlaskForm):
    """ Defines a new product form, which is a subclass of FlaskForm"""
    name = StringField('Product Name', validators=[DataRequired()])
    category = SelectField('Category', choices=[('chocolate', 'Chocolate'), ('strawberries', 'Chocolate Strawberries'), ('candies', 'Chocolate Candies'), ('statues', 'Chocolate Statues')], validators=[DataRequired()])
    price = FloatField('Price')
    weight = FloatField('Weight')
    image = FileField('Image File', validators=[DataRequired()])
    description = StringField('Description')
    keywords = StringField('Keywords')


@app.route('/chocoshop')
def store_page():
    """ Returns the main page of the Chocoshop online store """
    return render_template('store.html')


@login_manager.user_loader
def load_user(user_id):
    """
    Creates a user_loader callback to reload the User object from the user ID stored in the session
    :param user_id: the username
    :return User(user): the User object
    """
    users_docs = get_authorized_users()
    for user in users_docs:
        if user['username'] == user_id:
            return User(user)


@app.route('/login', methods=['GET', 'POST'])
def login():
    """
    Logins authorized users to the system.
    If successful, redirects to a webpage to add a new product on the website
    :return: user login webpage
    """
    login_form = LoginForm()
    if request.method == "POST":
        username = request.form.get('username')
        password = request.form.get('password')
        authorized_users = get_authorized_users()
        # checks for matching username and password with database records
        for user in authorized_users:
            if username == user['username'] and check_password_hash(user['password'], password):
                # create an instance of the  User class and pass it to flask_login.login_user()
                log_user = User(user)
                login_user(log_user)
                return redirect(url_for('add_product'))
            else:
                flash('Please check your username and password and try again.', 'danger')
    return render_template('login.html', form=login_form)


@app.route('/add', methods=['GET', 'POST'])
def add_product():
    """
    If user is authorized and logged into the system, opens a form to add a new product and
    sends entered information to the firestore database. Otherwise redirects user to login first.
    :return: webpage for adding a new product or redirect to the login webpage
    """
    if current_user.is_authenticated:
        product_form = ProductForm()
        if request.method == "POST":
            name = product_form.name.data
            category = product_form.category.data
            price = product_form.price.data
            weight = product_form.weight.data
            desc = product_form.description.data
            keywords = product_form.keywords.data

            image = request.files['image']
            filename = secure_filename(image.filename)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            # In order to load an image to the bucket, it first saves in to the temporary repository "uploaded_images",
            # then uploads the image from this folder to the bucket, and finally removes the image from the folder.
            image.save(filepath)
            name_to_save = name.replace(' ', '_').lower()
            upload_to_bucket(BUCKET_NAME, filepath, f"{category}/{name_to_save}")
            os.remove(filepath)

            image_ref = f"https://storage.cloud.google.com/{BUCKET_NAME}/{category}/{name_to_save}"

            upload_to_firestore(name, category, price, weight, image_ref, desc, keywords)
            return redirect(url_for('add_product'))
        return render_template('add_product.html', form=product_form)
    else:
        return redirect(url_for('login'))


@app.route('/products')
def category_products():
    """ Displays all products from the chosen category """
    category = request.args.get('category')
    return render_template('category_products.html', products=get_all_products(), category=category)


@app.route('/product')
def show_product():
    """ Displays a clicked product webpage"""
    product = ast.literal_eval(request.args.get('product'))
    add = request.args.get('add')
    if add:
        product = ast.literal_eval(request.args.get('product'))
        cart.append(product)
        print(cart)
    return render_template('product.html', product=product)


@app.route('/search', methods=['GET', 'POST'])
def search_products():
    """ Displays the search webpages with search results """
    if request.method == "POST":
        search_for = tuple(request.form['search'].split(' '))
        print(search_for)
        products = searched_products(search_for)
        print(products)
        return render_template('searched.html', products=products)


@app.route('/cart', methods=['GET', 'POST'])
def cart_products():
    """ Displays the cart webpage with added products"""
    total_amount = 0
    product_count = len(cart)
    for product in cart:
        total_amount += product['price']
    return render_template('cart.html', products=cart, amount=total_amount, count=product_count)


@app.route('/remove')
def remove_from_cart():
    """ Removes products from the cart """
    product_name = request.args.get('product_name')
    for product in cart:
        if product['name'] == product_name:
            cart.remove(product)
            break
    return redirect(url_for('cart_products'))


if __name__ == "__main__":
    app.run(debug=True)
