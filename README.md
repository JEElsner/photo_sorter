# photo_sorter

Sort photos from a bulk folder into subfolders by date, first by year, then by month.

Sort either locally on disk, or on OneDrive, using Microsoft's Graph API.

*Disclaimer: Like all publicly available code on the internet, use at your own risk. Inspect all code befor running. I'm not responsible if you accidentally delete all your photos, or if your computer explodes.*

## Purpose

I use OneDrive as my cloud storage solution. Microsoft offers a phone app which you can use to back up your Camera Roll. For years, this would back up every photo into just one folder. Recently, an option was added to back up new photos sorted into folders by year and month. This is great for the new photos I take, but I still have thousands of old photos still in one folder. This program aims to sort all those old photos into subfolders, just like the new ones.

## Security and Safety

As mentioned in the disclaimer, this software is presented AS-IS, and you alone are responsible for any problems you encounter. That being said, here are some safety considerations:

* Sortation is done locally, on your machine, and there is only communcation with OneDrive. At the risk of stating the obvious, none of your personal data is sent to me.
* When finished, you should delete `token.txt`, since that contains a Microsoft Graph access token. It will expire after a few hours, but it should be deleted to be sure.
* When finished, you should remove any app registrations in the Azure Active Directory. This way, no one can access your information if they obtain the app client ID
* Keep your client ID and tenant ID secret

## Installation and Setup

Steps 6 and 7 can be omitted if you are just sorting files locally

1. Ensure python 3 is installed
2. Clone the repository, or download the source code from the latest release
3. Create a new virtual environment in the source folder and activate it
4. Install dependencies by running: `pip install -r requirements.txt`
5. Install the module by runnning `pip install .`
7. Register the app on Microsoft Graph (see [Microsoft Registration](#microsoft-registration))
8. Paste the Client ID and tenant ID from the app registration into `auth_template.json` and rename it to `auth.json`

## Use

After completing the setup, run using `python -m PhotoSorter`, then follow the instructions in the terminal. If you sort photos on OneDrive, you will need to sign in to your Microsoft Account.

Sometimes OneDrive doesn't "find" all of the photos that need to be sorted on the first pass, so the module may need to be ran multiple times if you find that only a small percentage of your photos have been moved. Even after running several times, some of your photos probably will not be moved because they are lacking the necessary metadata to determine when they were taken. If it has been some time since you last ran the module, you will need to delete `token.txt` to reset the Microsoft account access.

## Microsoft Registration

Here's how to register an app on Microsoft Azure Active Directory (a.k.a. Microsoft Entra ID).

1. Navigate to the [Microsoft Azure Portal](https://portal.azure.com/)
2. Click on `Microsoft Entra ID` under `Azure Services`
3. Click on `App Registrations` in the left-hand sidebar under `Manage`
4. Click `New Registration` towards the top of the page
5. Fill out a name and select `Accounts in any organizational directory (Any Microsoft Entra ID tenant - Multitenant) and personal Microsoft accounts (e.g. Skype, Xbox)`, then click `Register`
6. Copy the `Application (client) ID` and `Directory (tenant) ID`, you will need these to complete [setup](#installation-and-setup) of the PhotoSorter
7. Click `Authentication` in the left-hand sidebar
8. Toggle `Allow public client flows` to `Yes` and Save

## Development

To set up for development, follow the same steps in the [Installation](#installation-and-setup) section, except use `pip install -e .` instead in step 5.

## License

See [LICENSE.md](https://github.com/JEElsner/photo_sorter/blob/main/LICENSE.md)
